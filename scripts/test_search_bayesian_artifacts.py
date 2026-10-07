#!/usr/bin/env python3
"""Verified matrix, unique budget and no-anticipation wall-clock gates."""
import collections
import gzip
import hashlib
import json
import math
import pathlib
import unittest

from search_bayesian_campaign import at_time, curve
from search_cpu import aggregate, identity


class BayesianArtifactTests(unittest.TestCase):
    def test_verified_unique_matrix_and_wall_clocks_reproduce_report(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / 'scripts/reports/search-bayesian.json').read_text())
        payload = (root / report['raw_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report['raw_ledger_sha256'])
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        self.assertEqual(len(rows), report['raw_rows'])
        measured = collections.defaultdict(list)
        for row in rows:
            measured[row['study'], row['trial_id']].append(row)
        cases = {c['path'].split('/')[-1]: c for c in report['corpus']['cases'] if c['partition'] == 'train'}
        expected_keys = set()
        for index, study in enumerate(report['studies']):
            self.assertFalse(study['validation_measured'])
            self.assertEqual(len(study['training']), report['protocol']['configured_trials'] + 4)
            self.assertEqual(len({t['id'] for t in study['training']}), len(study['training']))
            for trial in study['training']:
                expected_keys.add((index, trial['id']))
                observations = measured[index, trial['id']]
                self.assertEqual(len(observations), len(cases))
                self.assertEqual({r['input'] for r in observations}, set(cases))
                self.assertEqual(identity(trial['config']), trial['id'])
                self.assertEqual(aggregate(observations), trial['aggregate'])
                for row in observations:
                    self.assertEqual(row['raw_bytes'], cases[row['input']]['bytes'])
                    for field in ('samples_ns', 'baseline_samples_ns'):
                        self.assertEqual(len(row[field]), report['protocol']['training_rounds'])
                        self.assertTrue(all(math.isfinite(v) and v > 0 for v in row[field]))
                    for field in ('packed_sha256', 'baseline_packed_sha256'):
                        self.assertEqual(len(bytes.fromhex(row[field])), 32)
            self.assertEqual(curve(study, report['protocol']), study['curve'])
            self.assertEqual(at_time(study['curve'], report['common_horizon_seconds']), study['common_horizon'])
            for checkpoint, value in study['wall_checkpoints'].items():
                self.assertEqual(at_time(study['curve'], float(checkpoint)), value)
            if study['optimizer']:
                for trial in study['optimizer']['trials']:
                    self.assertEqual(trial['state'], 'COMPLETE')
                    self.assertIn(trial['config_id'], {t['id'] for t in study['training']})
                    self.assertEqual(len(trial['values']), 2)
        self.assertEqual(expected_keys, set(measured))
        self.assertEqual(report['common_horizon_seconds'], min(s['search_seconds'] for s in report['studies']))
        self.assertEqual(len({s['binary_sha256'] for s in report['studies']}), 1)
        self.assertFalse(report['reserved_test_measured'])
        self.assertEqual(report['promotion'], 'none')


if __name__ == '__main__':
    unittest.main()
