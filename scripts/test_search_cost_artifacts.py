#!/usr/bin/env python3
"""Reconstruct published parser evidence without native or optional dependencies."""
import collections
import gzip
import hashlib
import json
import math
import pathlib
import unittest

from search_cost_build import build
from search_cost_oracle import exact, expand, longest
from search_cpu import aggregate
from search_poc import decode_exact

ROOT = pathlib.Path(__file__).resolve().parents[1]


class CostArtifactTests(unittest.TestCase):
    def test_complete_paired_matrix_and_frozen_roles(self):
        report = json.loads((ROOT / 'scripts/reports/search-cost.json').read_text())
        payload = (ROOT / report['raw_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report['raw_ledger_sha256'])
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        self.assertEqual(len(rows), report['raw_rows'])
        self.assertEqual(len(rows), report['verified_rows'])
        measured = collections.defaultdict(list)
        for row in rows:
            measured[row['partition'], row['config_id']].append(row)
        keys = set()
        for event in report['training'] + report['validation']:
            partition = event['partition']
            key = partition, event['id']
            self.assertNotIn(key, keys)
            keys.add(key)
            cases = {pathlib.PurePosixPath(c['path']).name: c for c in report['corpus']['cases'] if c['partition'] == partition}
            observations = measured[key]
            self.assertEqual(len(observations), len(cases))
            self.assertEqual({r['input'] for r in observations}, set(cases))
            self.assertEqual(hashlib.sha256(json.dumps(event['config'], sort_keys=True).encode()).hexdigest(), event['id'])
            self.assertEqual(aggregate(observations), event['aggregate'])
            self.assertEqual(max(r['packed_bytes'] / r['baseline_bytes'] for r in observations), event['max_file_size_vs_balanced'])
            for row in observations:
                self.assertEqual(row['raw_bytes'], cases[row['input']]['bytes'])
                rounds = report['protocol']['training_rounds' if partition == 'train' else 'validation_rounds']
                for field in ('samples_ns', 'baseline_samples_ns'):
                    self.assertEqual(len(row[field]), rounds)
                    self.assertTrue(all(math.isfinite(v) and v > 0 for v in row[field]))
                for field in ('packed_sha256', 'baseline_packed_sha256'):
                    self.assertEqual(len(bytes.fromhex(row[field])), 32)
            for scope in ('real-regression-chunks', 'synthetic-regression', 'synthetic-extended'):
                selected = {name for name, c in cases.items() if
                            (scope == 'real-regression-chunks' and c['family'] == 'real') or
                            (scope == 'synthetic-regression' and c['family'] != 'real' and c['dataset'] == 'previous') or
                            (scope == 'synthetic-extended' and c['dataset'] == 'extended')}
                if selected:
                    self.assertEqual(aggregate([r for r in observations if r['input'] in selected]), event[scope]['aggregate'])
        self.assertEqual(keys, set(measured))
        self.assertEqual(report['finalists']['configs'], {e['id']: e['config'] for e in report['validation']})
        training = {e['id']: e for e in report['training']}
        eligible = [e for e in training.values() if e['max_file_size_vs_balanced'] <= report['protocol']['guardrails']['maximum_file_size_vs_balanced']]
        roles = report['finalists']['roles']
        self.assertEqual(roles['size'], min(eligible, key=lambda e: e['aggregate']['packed_bytes'])['id'])
        for role, bound in (('speed', 1.2), ('balanced', 1.01)):
            candidates = [e for e in eligible if e['aggregate']['size_vs_balanced'] <= bound]
            self.assertEqual(roles[role], max(candidates, key=lambda e: e['aggregate']['speed_vs_paired_balanced'])['id'])
        for partition in ('train', 'validation'):
            fixed = {e['config']['method']: measured[partition, e['id']] for e in report['training' if partition == 'train' else 'validation'] if e['config']['method'].endswith(':fixed')}
            greedy = {r['input']: r['packed_bytes'] for r in fixed['longest:16:4096:fixed']}
            for row in fixed['cost:16:4096:fixed']:
                self.assertLessEqual(row['packed_bytes'], greedy[row['input']])
        self.assertFalse(report['reserved_tests_encoded'])
        self.assertEqual(report['promotion'], 'none')

    def test_retained_exact_witnesses_and_geometry(self):
        report = json.loads((ROOT / 'scripts/reports/search-cost.json').read_text())
        self.assertEqual(len(report['exact_rows']), report['protocol']['exact_cases'])
        for row in report['exact_rows']:
            raw = bytes.fromhex(row['raw_hex'])
            oracle = exact(raw)
            self.assertEqual(oracle['fixed_bits'], row['oracle']['fixed_bits'])
            self.assertEqual(longest(raw)['fixed_bits'], row['greedy']['fixed_bits'])
            self.assertEqual(oracle['fixed_bits'], row['native']['fixed_bits'])
            self.assertLessEqual(oracle['fixed_bits'], row['greedy']['fixed_bits'])
            for kind in ('oracle', 'greedy', 'native'):
                self.assertEqual(expand(row[kind]['tokens']), raw)
                self.assertEqual((row[kind]['fixed_bits'] + 7) // 8, row[kind]['packed_bytes'])
            packed = bytes.fromhex(row['native']['packed_hex'])
            self.assertEqual(len(packed), row['native']['packed_bytes'])
            decode_exact(packed, raw)
        self.assertEqual(len(report['builds']), len(report['protocol']['geometry']))
        for record in report['builds'].values():
            layout = record['layout']
            self.assertIn(layout['position_bits'], (32, 64))
            self.assertEqual(layout['table_bytes'], (layout['position_bits'] // 8) * ((1 << layout['hash_bits']) + layout['window_bytes']))
            self.assertEqual(len(bytes.fromhex(record['binary_sha256'])), 32)
        # Invalid knobs fail before invoking compiler/build work.
        for layout in ({'hash_bits': True, 'window_bytes': 1024}, {'hash_bits': 19, 'window_bytes': 1024},
                       {'hash_bits': 12, 'window_bytes': 1025}, {'hash_bits': 12, 'window_bytes': 65536},
                       {'hash_bits': 12, 'window_bytes': 1024, 'unused': 1}):
            with self.assertRaises(ValueError):
                build(layout)


if __name__ == '__main__':
    unittest.main()
