#!/usr/bin/env python3
"""Wall-time accounting never anticipates or extrapolates verified outcomes."""
import unittest

from search_bayesian_campaign import at_time, curve


class WallClockTests(unittest.TestCase):
    def test_only_completed_trials_contribute_and_stopped_runs_are_censored(self):
        study = {'training': [{}] * 4 + [
            {'search_elapsed_seconds': 2, 'aggregate': {'time_vs_paired_balanced': .5, 'size_vs_balanced': 1.1}},
            {'search_elapsed_seconds': 5, 'aggregate': {'time_vs_paired_balanced': .6, 'size_vs_balanced': .9}}]}
        protocol = {'hypervolume_anchor': [1, 1], 'hypervolume_reference': [4, 1.5]}
        values = curve(study, protocol)
        self.assertEqual(at_time(values, 1)['unique_evaluations'], 0)
        self.assertEqual(at_time(values, 4)['unique_evaluations'], 1)
        self.assertEqual(at_time(values, 5)['unique_evaluations'], 2)
        with self.assertRaises(ValueError):
            at_time(values, 6)
        study['training'][-1]['search_elapsed_seconds'] = 1
        with self.assertRaises(ValueError):
            curve(study, protocol)


if __name__ == '__main__':
    unittest.main()
