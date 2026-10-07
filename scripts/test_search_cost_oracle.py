#!/usr/bin/env python3
"""Independent parse enumeration and optional actual native fixed-cost witness."""
import argparse
import itertools
import json
import pathlib
import random
import subprocess
import tempfile
import unittest

from search_cost_oracle import exact, expand, longest, match_bits
from search_poc import decode_exact

BINARY = None


def enumerate_parses(raw):
    # Forward enumeration, no suffix-DP recurrence or cached state. Deliberately
    # spell out match validity and literal costs independently of oracle edges.
    frontier = [(0, 10)]
    best = float('inf')
    while frontier:
        pos, bits = frontier.pop()
        if pos == len(raw):
            best = min(best, bits)
            continue
        frontier.append((pos + 1, bits + (8 if raw[pos] < 144 else 9)))
        for length in range(3, min(258, len(raw) - pos) + 1):
            for distance in range(1, min(32768, pos) + 1):
                if all(raw[pos + k] == raw[pos + k - distance] for k in range(length)):
                    frontier.append((pos + length, bits + match_bits(length, distance)))
    return best


class CostOracleTests(unittest.TestCase):
    def test_exact_oracle_matches_exhaustive_parse_enumeration(self):
        for size in range(9):
            for symbols in itertools.product((0, 255), repeat=size):
                raw = bytes(symbols)
                parsed = exact(raw)
                self.assertEqual(parsed['fixed_bits'], enumerate_parses(raw))
                self.assertEqual(parsed['packed_bytes'], (parsed['fixed_bits'] + 7) // 8)
                self.assertEqual(expand(parsed['tokens']), raw)
                self.assertLessEqual(parsed['fixed_bits'], longest(raw)['fixed_bits'])

    def test_illegal_distances_lengths_and_reaches_are_rejected(self):
        for length, distance in ((2, 1), (259, 1), (3, 0), (3, 32769)):
            with self.assertRaises(ValueError):
                match_bits(length, distance)
        with self.assertRaises(ValueError):
            expand([('m', 3, 1)])
        with self.assertRaises(ValueError):
            exact(b'x' * 4097)

    def test_native_exact_cost_matches_python_oracle(self):
        if not BINARY:
            self.skipTest('pass --binary after building the native cost_parse example')
        rng = random.Random(195115)
        samples = [b'', b'x', b'aaa', bytes(range(256)), b'abracadabra' * 30]
        samples += [bytes(rng.choice((0, 1, 144, 255)) for _ in range(size)) for size in (4, 8, 12, 31, 96) for _ in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'case.raw'
            for raw in samples:
                path.write_bytes(raw)
                measured = json.loads(subprocess.check_output([BINARY, '--tokens', str(path), 'exact'], text=True))
                self.assertEqual(measured['fixed_bits'], exact(raw)['fixed_bits'])
                self.assertEqual(expand(measured['tokens']), raw)
                decode_exact(bytes.fromhex(measured['packed_hex']), raw)

    def test_bounded_cost_is_valid_and_no_worse_than_longest_on_same_graph(self):
        if not BINARY:
            self.skipTest('pass --binary for the native bounded-parser checks')
        rng = random.Random(195116)
        template = rng.randbytes(257)
        inputs = [rng.randbytes(4097), (template * 511)[:131073], b'abcabcabxabc' * 400]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'case.raw'
            for raw in inputs:
                path.write_bytes(raw)
                for block in (512, 4096, 16384):
                    measured = [json.loads(subprocess.check_output([BINARY, '--tokens', str(path), f'{kind}:16:{block}:fixed'], text=True))
                                for kind in ('longest', 'cost')]
                    self.assertLessEqual(measured[1]['fixed_bits'], measured[0]['fixed_bits'])
                    for row in measured:
                        self.assertEqual(expand(row['tokens']), raw)
                        decode_exact(bytes.fromhex(row['packed_hex']), raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary')
    args, remaining = parser.parse_known_args()
    BINARY = str(pathlib.Path(args.binary).resolve()) if args.binary else None
    unittest.main(argv=[__file__, *remaining])
