#!/usr/bin/env python3
"""S5 evidence integrity and split isolation, without performance thresholds."""
import gzip
import hashlib
import json
import math
import pathlib
import statistics
import unittest

from search_cpu import aggregate, worker_method
from search_policy import choose, serialize


class PolicyArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = pathlib.Path(__file__).resolve().parents[1]
        cls.report = json.loads((root / 'scripts/reports/search-policy.json').read_text())
        payload = (root / cls.report['raw_ledger']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != cls.report['raw_ledger_sha256']:
            raise ValueError('policy ledger hash mismatch')
        cls.rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]

    def test_complete_paired_evidence_reproduces_aggregates_and_training_labels(self):
        report = self.report
        self.assertEqual(len(self.rows), report['raw_rows'])
        self.assertEqual(report['raw_rows'], report['verified_rows'])
        cases = {p: {pathlib.PurePosixPath(c['path']).name: c for c in report['corpus']['cases']
                     if c['partition'] == p} for p in ('train', 'validation')}
        events = report['training_events'] + report['validation'] + report['controls']
        measured = {}
        for row in self.rows:
            measured.setdefault(row['label'], []).append(row)
        self.assertEqual(set(measured), {e['label'] for e in events})
        for event in events:
            rows = measured[event['label']]
            expected = cases[event['partition']]
            self.assertEqual(len(rows), len(expected))
            self.assertEqual({r['input'] for r in rows}, set(expected))
            self.assertEqual(aggregate(rows), event['aggregate'])
            rounds = report['protocol']['training_rounds' if event['partition'] == 'train' else 'validation_rounds']
            for row in rows:
                self.assertEqual(row['raw_bytes'], expected[row['input']]['bytes'])
                for key in ('samples_ns', 'baseline_samples_ns'):
                    self.assertEqual(len(row[key]), rounds)
                    self.assertTrue(all(math.isfinite(v) and v > 0 for v in row[key]))
                for key in ('packed_sha256', 'baseline_packed_sha256'):
                    self.assertEqual(len(bytes.fromhex(row[key])), 32)
        maps = [{r['input']: r for r in measured[e['label']]} for e in report['training_events']]
        for case in report['matrix']:
            name = pathlib.PurePosixPath(case['id']).name
            rows = [m[name] for m in maps]
            baseline_ns = statistics.median(statistics.median(r['baseline_samples_ns']) for r in rows)
            self.assertEqual(case['baseline_ns'], baseline_ns)
            self.assertEqual(case['baseline_bytes'], rows[0]['baseline_bytes'])
            for label, row in zip(case['measurements'], rows):
                self.assertEqual(label['packed_bytes'], row['packed_bytes'])
                self.assertEqual(label['packed_sha256'], row['packed_sha256'])
                self.assertEqual(label['encode_ns'], statistics.median(row['samples_ns']) / statistics.median(row['baseline_samples_ns']) * baseline_ns)
        self.assertFalse(report['test_partition_measured'])
        self.assertEqual(report['promotion'], 'none')
        self.assertEqual(sum(c['partition'] == 'test' for c in report['corpus']['cases']), 26)

    def test_frozen_trees_and_grouped_folds_are_consistent(self):
        report = self.report
        cases = {c['id']: c for c in report['matrix']}
        methods = [worker_method(c) for c in report['protocol']['vocabulary']]
        for role, fitted in report['fitted'].items():
            text = serialize(fitted['tree'], methods)
            self.assertEqual(text, report['native_policies'][role])
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), report['policy_sha256'][role])
            held = []
            for fold in fitted['outer']:
                self.assertFalse(set(fold['training_groups']) & set(fold['held_groups']))
                self.assertEqual(set(fold['training_groups']) | set(fold['held_groups']), {c['group'] for c in cases.values()})
                held.extend(fold['held_case_ids'])
                expected = [choose(fold['tree'], cases[key]) for key in fold['held_case_ids']]
                self.assertEqual(expected, fold['held_result']['choices'])
                self.assertEqual({cases[key]['group'] for key in fold['held_case_ids']}, set(fold['held_groups']))
            self.assertEqual(len(held), len(cases))
            self.assertEqual(set(held), set(cases))


if __name__ == '__main__':
    unittest.main()
