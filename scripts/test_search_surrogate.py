#!/usr/bin/env python3
"""Partition/calibration safety checks, with no MLX dependency."""
import json
import pathlib
import unittest

from search_surrogate_data import config_vector, group_quantile, load_training, partitions


class SurrogateTests(unittest.TestCase):
    def test_categorical_masks_distinguish_methods_and_reject_inactive_fields(self):
        base = config_vector({'preset': 'balanced'})
        self.assertEqual(base[:5], [1, 0, 0, 0, 0])
        self.assertFalse(any(base[5:]))
        with self.assertRaises(ValueError):
            config_vector({'preset': 'stored', 'probes': 16})
        with self.assertRaises(ValueError):
            config_vector({'reference': 'miniz1'})

    def test_partitions_preserve_source_and_config_isolation(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        records, provenance = load_training(root)
        protocol = json.loads((root / 'scripts/search_surrogate_protocol.json').read_text())
        plans = partitions(records, protocol)
        seen = []
        for plan in plans:
            fit, calibration, held = (set(plan[key]) for key in ('fit', 'calibration', 'held'))
            self.assertFalse(fit & held or fit & calibration or held & calibration)
            for key, groups in (('fit', 'fit_groups'), ('calibration', 'calibration_groups'), ('held', 'held_groups')):
                self.assertEqual({records[i]['group'] for i in plan[key]}, set(plan[groups]))
            self.assertFalse(set(plan['fit_groups']) & set(plan['held_groups']))
            unseen = set(plan['unseen_configs'])
            self.assertFalse({records[i]['config_id'] for i in fit | calibration} & unseen)
            seen.extend(held)
        self.assertEqual(len(seen), len(records))
        self.assertEqual(set(seen), set(range(len(records))))
        self.assertFalse(provenance['validation_or_test_labels_used'])
        # Changing target values cannot change assignments or categorical inputs.
        for record in records:
            record['y'] = [99999, -99999]
        self.assertEqual(partitions(records, protocol), plans)

    def test_group_quantile_handles_small_samples_without_false_finite_bounds(self):
        self.assertEqual(group_quantile([1, 4, 2, 5, 3], .8), 5)
        with self.assertRaises(ValueError):
            group_quantile([1, 2, 3], .95)


if __name__ == '__main__':
    unittest.main()
