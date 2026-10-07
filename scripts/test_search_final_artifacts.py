#!/usr/bin/env python3
"""Final matrix, genuine rotation, paired CIs, RSS and frozen guard decisions."""
import collections
import gzip
import hashlib
import json
import math
import pathlib
import statistics
import unittest

from search_final_campaign import parse_rss
from search_final_report import gates
from search_final_stats import direct, summary

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FinalArtifactTests(unittest.TestCase):
    def test_complete_matrix_rotates_positions_and_pairs(self):
        report = json.loads((ROOT / 'scripts/reports/search-final.json').read_text())
        payload = (ROOT / report['raw_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report['raw_ledger_sha256'])
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        cases = {c['path']: c for c in report['corpus']['cases']}
        names = set(report['finalists']['methods'])
        sessions = set(range(report['protocol']['sessions']))
        self.assertEqual(len(rows), report['raw_rows'])
        self.assertEqual(len(rows), len(cases) * len(names) * len(sessions))
        self.assertEqual(len(rows), report['verified_rows'])
        keys, grouped, pairs = set(), collections.defaultdict(list), collections.defaultdict(list)
        for row in rows:
            key = row['session'], row['method'], row['input']
            self.assertNotIn(key, keys)
            keys.add(key)
            self.assertIn(row['session'], sessions)
            self.assertIn(row['method'], names)
            case = cases[row['input']]
            self.assertEqual(row['raw_bytes'], case['bytes'])
            self.assertEqual(row['scope'], case['scope'])
            self.assertEqual(report['corpus']['cases'][row['original_case_index']]['path'], row['input'])
            for field in ('encode_ns', 'baseline_encode_ns', 'decode_ns', 'baseline_decode_ns',
                          'cold_encode_ns', 'cold_baseline_encode_ns', 'cold_decode_ns', 'cold_baseline_decode_ns'):
                self.assertTrue(math.isfinite(row[field]) and row[field] > 0)
            self.assertTrue(all(v > 0 for v in row['encode_iterations'] + row['decode_iterations']))
            for field in ('packed_sha256', 'baseline_packed_sha256'):
                self.assertEqual(len(bytes.fromhex(row[field])), 32)
            pairs[row['method'], row['input']].append(row)
            grouped[row['method']].append(row)
        self.assertEqual(keys, {(s, n, c) for s in sessions for n in names for c in cases})
        for observations in pairs.values():
            self.assertEqual(len({r['method_order'] for r in observations}), len(sessions))
            self.assertEqual(sum(r['pair_order'] == 0 for r in observations), len(sessions) // 2)
            self.assertEqual(sum(r['pair_order'] == 1 for r in observations), len(sessions) // 2)
            for field in ('packed_bytes', 'baseline_bytes', 'packed_sha256', 'baseline_packed_sha256'):
                self.assertEqual(len({r[field] for r in observations}), 1)
        seed = report['protocol']['seed']
        for name, observations in grouped.items():
            for scope in ('fresh', 'tiny'):
                self.assertEqual(summary([r for r in observations if r['scope'] == scope], seed), report['metrics'][name][scope])
        for name in report['protocol']['roles'].values():
            for ref in ('balanced', 'best', 'miniz1', 'miniz6', 'miniz9'):
                for scope in ('fresh', 'tiny'):
                    self.assertEqual(direct([r for r in grouped[name] if r['scope'] == scope], [r for r in grouped[ref] if r['scope'] == scope], seed), report['direct_references'][name][ref][scope])
            self.assertEqual(gates(name, report, report['metrics'][name], report['direct_references'][name]), report['decisions'][name])
        self.assertFalse(report['adaptive_test_feedback'])

    def test_rss_size_probe_and_aborted_attempt_integrity(self):
        report = json.loads((ROOT / 'scripts/reports/search-final.json').read_text())
        names = set(report['finalists']['methods'])
        rss = collections.defaultdict(list)
        for record in report['rss']:
            rss[record['method'], record['case']['path']].append(record)
            self.assertEqual(parse_rss(record['time_stderr'], 'Darwin' if 'Darwin' in report['platform'] or 'macOS' in report['platform'] else 'Linux'), record['peak_rss_bytes'])
            self.assertEqual(record['native']['raw_bytes'], record['case']['bytes'])
            self.assertGreater(record['peak_rss_bytes'], 0)
        self.assertEqual({name for name, _ in rss}, names)
        self.assertEqual(len(rss), 3 * len(names))
        for group in rss.values():
            self.assertEqual(len(group), report['protocol']['rss_repeats'])
            self.assertEqual({r['repeat'] for r in group}, set(range(report['protocol']['rss_repeats'])))
            self.assertEqual(len({r['packed_sha256'] for r in group}), 1)
        self.assertEqual(set(report['size_builds']), names)
        for name, builds in report['size_builds'].items():
            self.assertEqual(set(builds), {'release', 'min'})
            self.assertEqual(len({v['probe_packet_sha256'] for v in builds.values()}), 1)
            for build in builds.values():
                self.assertEqual(build['total_bytes'], build['binary_bytes'] + build['external_policy_bytes'])
                self.assertEqual(build['external_policy_bytes'], len(report['finalists']['methods'][name].get('policy', '').encode()))
                for field in ('binary_sha256', 'probe_packet_sha256', 'probe_raw_sha256'):
                    self.assertEqual(len(bytes.fromhex(build[field])), 32)
        abandoned = ROOT / report['aborted_attempt']['report']
        self.assertEqual(hashlib.sha256(abandoned.read_bytes()).hexdigest(), report['aborted_attempt']['sha256'])
        abort = json.loads(abandoned.read_text())
        ledger = (ROOT / abort['raw_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(ledger).hexdigest(), abort['raw_ledger_sha256'])
        self.assertEqual(len(gzip.decompress(ledger).splitlines()), abort['rows'])
        self.assertFalse(abort['measurements_used_for_selection_or_threshold_changes'])
        self.assertEqual(abort['protocol'], report['protocol'])
        for name, method in report['finalists']['methods'].items():
            previous = abort['finalists']['methods'][name]
            self.assertEqual(method.get('config'), previous.get('config'))
            self.assertEqual(method.get('policy'), previous.get('policy'))
            if 'policy' not in method:
                self.assertEqual(method['worker'], previous['worker'])
        model_path = ROOT / report['model_correspondence']['report']
        self.assertEqual(hashlib.sha256(model_path.read_bytes()).hexdigest(), report['model_correspondence']['sha256'])
        model = json.loads(model_path.read_text())
        self.assertEqual(model['final_binary_sha256'], report['binary_sha256'])
        self.assertEqual(model['packets'], len(model['records']))
        self.assertEqual(model['packets'], report['model_correspondence']['packets'])
        cost = json.loads((ROOT / 'scripts/reports/search-cost.json').read_text())
        mixed = json.loads((ROOT / 'scripts/reports/search-mixed.json').read_text())
        self.assertEqual(collections.Counter(r['study'] for r in model['records']),
                         {'S7': len(cost['exact_rows']), 'S8': len(mixed['witnesses']),
                          'S9': sum(c['scope'] == 'tiny' or c['family'] == 'real' for c in report['corpus']['cases']) * len(names)})
        for record in model['records']:
            self.assertEqual(record['lean_decoded_sha256'], record['raw_sha256'])
            self.assertEqual(record['rust_decoded_sha256'], record['raw_sha256'])
        policy = (ROOT / report['retained_size_policy']['path']).read_bytes()
        self.assertEqual(hashlib.sha256(policy).hexdigest(), report['retained_size_policy']['sha256'])
        self.assertEqual(policy.decode(), report['finalists']['methods']['policy-size']['policy'])


if __name__ == '__main__':
    unittest.main()
