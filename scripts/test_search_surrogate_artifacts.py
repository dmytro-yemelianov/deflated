#!/usr/bin/env python3
"""Check published predictions, frozen groups, calibration and model hashes."""
import collections
import gzip
import hashlib
import json
import math
import pathlib
import statistics
import unittest
import zipfile

from search_surrogate_data import group_quantile, load_training


class SurrogateArtifactTests(unittest.TestCase):
    def test_prediction_matrix_and_group_metrics_are_reproducible(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / 'scripts/reports/search-surrogate.json').read_text())
        payload = (root / report['prediction_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report['prediction_ledger_sha256'])
        records, provenance = load_training(root)
        self.assertEqual(provenance, report['provenance'])
        by_id = {r['id']: r for r in records}
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        self.assertEqual(len(rows), report['prediction_rows'])
        self.assertEqual(len(rows), 3 * len(records))
        self.assertEqual(len({(r['model'], r['id']) for r in rows}), len(rows))
        partition = {p['fold']: p for p in report['partitions']}
        errors = collections.defaultdict(list)
        for row in rows:
            original = by_id[row['id']]
            self.assertEqual(row['target_log'], original['y'])
            self.assertEqual(row['group'], original['group'])
            plan = partition[row['fold']]
            self.assertIn(row['group'], plan['held_groups'])
            self.assertNotIn(row['group'], plan['fit_groups'] + plan['calibration_groups'])
            self.assertEqual(row['config_unseen'], row['config_id'] in plan['unseen_configs'])
            self.assertTrue(all(math.isfinite(v) for member in row['predicted_members_log'] for v in member))
            self.assertTrue(all(math.isfinite(v) and v >= 0 for v in row['interval_half_width_log']))
            error = [abs(statistics.mean(member[a] for member in row['predicted_members_log']) - row['target_log'][a]) for a in (0, 1)]
            errors[row['fold'], row['model'], row['group']].append(error)
        for entry in report['fold_results']:
            for group in entry['metrics']['groups']:
                measured = errors[entry['fold'], entry['model'], group['group']]
                for axis in (0, 1):
                    self.assertAlmostEqual(statistics.mean(e[axis] for e in measured), group['mae_log'][axis], delta=3e-6)
            calibration = entry['calibration']
            self.assertEqual(set(calibration['group_max_scores']), set(partition[entry['fold']]['calibration_groups']))
            self.assertEqual(group_quantile(list(calibration['group_max_scores'].values()), calibration['coverage_target']), calibration['quantile'])
        archive = (root / report['model_archive']).read_bytes()
        self.assertEqual(hashlib.sha256(archive).hexdigest(), report['model_archive_sha256'])
        with zipfile.ZipFile(root / report['model_archive']) as models:
            self.assertEqual(set(models.namelist()), set(report['model_sha256']))
            for name, digest in report['model_sha256'].items():
                self.assertEqual(hashlib.sha256(models.read(name)).hexdigest(), digest)
        self.assertFalse(report['reserved_tests_measured'])
        self.assertEqual(report['promotion'], 'none')


if __name__ == '__main__':
    unittest.main()
