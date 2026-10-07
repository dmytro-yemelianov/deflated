#!/usr/bin/env python3
"""Session statistics, platform RSS units and actual final-worker parity."""
import argparse
import json
import pathlib
import subprocess
import tempfile
import unittest

from search_final_campaign import parse_rss, schedule
from search_final_stats import direct, summary
from search_poc import decode_exact

BINARY = None


class FinalTests(unittest.TestCase):
    def test_rotation_does_not_cancel_when_file_order_rotates(self):
        names = [str(i) for i in range(11)]
        for original_case_index in (0, 1, 9, 10, 62):
            positions = {name: set() for name in names}
            orders = {name: [] for name in names}
            for session in range(10):
                order = schedule(session, original_case_index, names)
                self.assertEqual({name for name, _ in order}, set(names))
                for position, (name, pair_order) in enumerate(order):
                    positions[name].add(position)
                    orders[name].append(pair_order)
            for name in names:
                self.assertEqual(len(positions[name]), 10)
                self.assertEqual(orders[name].count(0), 5)
                self.assertEqual(orders[name].count(1), 5)
    def test_platform_rss_units_and_missing_measurement(self):
        self.assertEqual(parse_rss('  12345 maximum resident set size\n', 'Darwin'), 12345)
        self.assertEqual(parse_rss('Maximum resident set size (kbytes): 12345\n', 'Linux'), 12345 * 1024)
        with self.assertRaises(ValueError):
            parse_rss('no RSS', 'Darwin')

    def test_session_pairs_and_direct_reference_retain_exact_scaling(self):
        rows = []
        for session in range(10):
            for name, size in (('small', 10), ('large', 1000)):
                ns = (session + 1) * size
                row = {'session': session, 'input': name, 'raw_bytes': size, 'packed_bytes': 5, 'baseline_bytes': 10,
                       'encode_ns': ns, 'baseline_encode_ns': 2 * ns, 'decode_ns': ns, 'baseline_decode_ns': 3 * ns,
                       'cold_encode_ns': 4 * ns, 'cold_baseline_encode_ns': 8 * ns, 'cold_decode_ns': ns, 'cold_baseline_decode_ns': 3 * ns}
                rows.append(row)
        result = summary(rows, resamples=100)
        self.assertEqual(result['warm_speed_vs_balanced'], 2)
        self.assertEqual(result['session_bootstrap_95pct']['warm_speed'], [2, 2])
        self.assertEqual(result['session_bootstrap_95pct']['cold_speed'], [2, 2])
        self.assertEqual(result['size_vs_balanced'], 0.5)
        identity = direct(rows, rows, resamples=100)
        self.assertEqual(identity['warm_speed_vs_reference'], 1)
        self.assertEqual(identity['size_vs_reference'], 1)
        self.assertEqual(identity['session_bootstrap_95pct']['warm_speed'], [1, 1])

    def test_native_warm_cold_memory_and_references_agree(self):
        if not BINARY:
            self.skipTest('pass --binary after building final_bench with research-tuning')
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path, out = root / 'input.raw', root / 'streams'
            policy = root / 'policy.txt'
            policy.write_text('policy-v1 features-13 short-balanced-32768\nL config:16:1:0:trigram:16384\n')
            size_policy = root / 'size-policy.txt'
            size_policy.write_text('policy-v1 features-13 short-balanced-32768\nB 2 273.5 1 2\nL config:1024:1:0:trigram:16384\nL best\n')
            methods = ('balanced', 'best', 'fast', 'config:1:0:8:trigram:16384', 'config:32:0:16:trigram:16384',
                       'config:128:1:0:trigram:16384', 'miniz1', 'miniz6', 'miniz9', 'policy@' + str(policy), 'policy@' + str(size_policy))
            for raw in (b'', b'abcabc' * 17, b'abc' * 12000, bytes(range(256)) * 200):
                path.write_bytes(raw)
                for method in methods:
                    packets = []
                    for mode in ('warm', 'cold'):
                        row = json.loads(subprocess.check_output([BINARY, mode, str(path), str(out), '1', method, '1'], text=True))
                        packet = (out / 'candidate.deflate').read_bytes()
                        packets.append(packet)
                        decode_exact(packet, raw)
                        self.assertEqual(row['packed_bytes'], len(packet))
                        self.assertGreater(row['encode_ns'], 0)
                        self.assertGreater(row['decode_ns'], 0)
                        if mode == 'warm':
                            self.assertTrue(all(n > 0 for n in row['encode_iterations'] + row['decode_iterations']))
                            decode_exact((out / 'baseline.deflate').read_bytes(), raw)
                    memory = root / 'memory.deflate'
                    subprocess.check_output([BINARY, '--memory', str(path), str(memory), method])
                    self.assertEqual(memory.read_bytes(), packets[0])
                    self.assertEqual(packets[0], packets[1])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary')
    args, remaining = parser.parse_known_args()
    BINARY = str(pathlib.Path(args.binary).resolve()) if args.binary else None
    unittest.main(argv=[__file__, *remaining])
