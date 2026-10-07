#!/usr/bin/env python3
"""Exhaustive alignment oracle and actual native mixed-stream witnesses."""
import argparse
import itertools
import json
import pathlib
import random
import subprocess
import tempfile
import unittest

from search_poc import decode_exact

BINARY = None


def stored_bits(raw, offset):
    # Round the position after BFINAL/BTYPE up to the next byte; LEN/NLEN
    # contribute four bytes. Additional <=65535-byte blocks begin aligned.
    first = ((offset + 3 + 7) // 8) * 8 - offset
    return first + 32 + raw * 8 + max(0, (raw + 65534) // 65535 - 1) * 40


def exhaustive(costs, start, stored=True):
    best = float('inf')
    for kinds in itertools.product(('Fixed', 'Dynamic', 'Stored') if stored else ('Fixed', 'Dynamic'), repeat=len(costs)):
        offset, total, valid = start, 0, True
        for (fixed, dynamic, raw), kind in zip(costs, kinds):
            bits = fixed if kind == 'Fixed' else dynamic if kind == 'Dynamic' else stored_bits(raw, offset)
            if bits is None:
                valid = False
                break
            total += bits
            offset = (offset + bits) % 8
        if valid:
            best = min(best, total + (8 - offset) % 8)
    return best


class MixedTests(unittest.TestCase):
    def test_stored_boundary_costs(self):
        for offset in range(8):
            self.assertEqual(stored_bits(65536, offset) - stored_bits(65535, offset), 48)
            self.assertEqual((offset + stored_bits(0, offset)) % 8, 0)
            self.assertEqual(stored_bits(0, 0), 40)

    def test_native_plan_matches_all_type_sequences_at_every_offset(self):
        if not BINARY:
            self.skipTest('pass --binary after building mixed_blocks')
        rng = random.Random(195118)
        for count in range(1, 8):
            costs = [(rng.randrange(10, 1200), None if i % 3 == 0 else rng.randrange(20, 1400), rng.randrange(0, 140)) for i in range(count)]
            for start in range(8):
                text = ';'.join(f'{f},{d if d is not None else "_"},{r}' for f, d, r in costs)
                native = json.loads(subprocess.check_output([BINARY, '--plan', str(start), text], text=True))
                self.assertEqual(native['bits'], exhaustive(costs, start))
        for raw in (0, 65534, 65535, 65536, 131070, 131071):
            for start in range(8):
                native = json.loads(subprocess.check_output([BINARY, '--plan', str(start), f'999999,_,{raw}'], text=True))
                self.assertEqual(native['bits'], exhaustive([(999999, None, raw)], start))

    def test_native_packets_and_cross_block_history(self):
        if not BINARY:
            self.skipTest('pass --binary for actual packet checks')
        rng = random.Random(195119)
        history = rng.randbytes(32768)
        cases = [b'', b'x', bytes(range(256)), rng.randbytes(65536), b'x' * 131073,
                 history + history + b'x' * 65536 + rng.randbytes(65537),
                 rng.randbytes(16384) + b'abc' * 32768 + rng.randbytes(16385)]
        stored_seen, compressed_seen = False, False
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'input.raw'
            for raw in cases:
                path.write_bytes(raw)
                for level in ('fast', 'balanced', 'best'):
                    for count in (1024, 4096, 16384):
                        evidence = [json.loads(subprocess.check_output([BINARY, '--inspect', str(path), f'{kind}:{level}:{count}'], text=True)) for kind in ('compressed', 'mixed')]
                        self.assertLessEqual(len(bytes.fromhex(evidence[1]['packed_hex'])), len(bytes.fromhex(evidence[0]['packed_hex'])))
                        for row in evidence:
                            packed = bytes.fromhex(row['packed_hex'])
                            decode_exact(packed, raw)
                            self.assertEqual(len(packed), (row['emitted_bits'] + 7) // 8)
                            if row['fallback']:
                                self.assertEqual(len(packed), len(raw) + max(1, (len(raw) + 65534) // 65535) * 5)
                            else:
                                self.assertEqual(len(packed) * 8, row['planned_bits'])
                                self.assertEqual(sum(b['raw_bytes'] for b in row['blocks']), len(raw))
                                offset, bits = 0, 0
                                for block in row['blocks']:
                                    self.assertEqual(offset, block['start_offset'])
                                    cost = block['fixed_bits'] if block['kind'] == 'Fixed' else block['dynamic_bits'] if block['kind'] == 'Dynamic' else stored_bits(block['raw_bytes'], offset)
                                    self.assertEqual(cost, block['emitted_bits'])
                                    offset = (offset + cost) % 8
                                    bits += cost
                                    stored_seen |= block['kind'] == 'Stored'
                                    compressed_seen |= block['kind'] != 'Stored'
                                self.assertEqual(bits, row['emitted_bits'])
            self.assertTrue(stored_seen)
            self.assertTrue(compressed_seen)

    def test_invalid_native_knobs_fail(self):
        if not BINARY:
            self.skipTest('pass --binary for native parser rejection')
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'input.raw'
            path.write_bytes(b'abc')
            for method in ('mixed:balanced:0', 'mixed:balanced:16385', 'mixed:bogus:1024', 'mixed:balanced:1024:extra'):
                run = subprocess.run([BINARY, '--inspect', str(path), method], capture_output=True)
                self.assertNotEqual(run.returncode, 0)

    def test_stored_packets_at_all_offsets_and_len_boundaries(self):
        if not BINARY:
            self.skipTest('pass --binary for actual stored-block boundary packets')
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'input.raw'
            for size in (0, 65535, 65536, 131071):
                raw = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
                path.write_bytes(raw)
                for count in range(8):
                    row = json.loads(subprocess.check_output([BINARY, '--stored-probe', str(path), str(count)], text=True))
                    self.assertEqual(row['offset'], (10 + 9 * count) % 8)
                    packet = bytes.fromhex(row['packed_hex'])
                    self.assertEqual(len(packet) * 8, 10 + 9 * count + stored_bits(size, row['offset']))
                    decode_exact(packet, bytes([144]) * count + raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary')
    args, remaining = parser.parse_known_args()
    BINARY = str(pathlib.Path(args.binary).resolve()) if args.binary else None
    unittest.main(argv=[__file__, *remaining])
