#!/usr/bin/env python3
"""Optional NSGA-II adapter checks; run in the pinned research environment."""
import unittest

from search_cpu import identity
from search_optimizer import NSGAProposer, TPEProposer


class OptimizerTests(unittest.TestCase):
    def test_unique_budget_reuses_verified_duplicates_and_fails_without_score(self):
        optimizer = NSGAProposer(17)
        trials = []
        for index in range(32):
            config = optimizer.ask(trials)
            key = identity(config)
            self.assertNotIn(key, {t["id"] for t in trials})
            result = {"id": key, "config": config,
                      "aggregate": {"time_vs_paired_balanced": 1 + index / 100, "packed_bytes": 10000 - index}}
            optimizer.tell(result)
            trials.append(result)
            if index == 0:
                optimizer.study.enqueue_trial(config)
        self.assertGreaterEqual(optimizer.cached, 1)
        first = trials[0]
        cached = [t for t in optimizer.study.trials if t.user_attrs["config_id"] == first["id"]]
        self.assertEqual(len(cached), 2)
        self.assertEqual(cached[0].values, cached[1].values)
        optimizer.ask(trials)
        optimizer.fail()
        self.assertIsNone(optimizer.study.trials[-1].values)
        self.assertEqual(optimizer.study.trials[-1].state.name, "FAIL")

    def test_tpe_conditional_space_unique_trials_cached_feedback_and_failure(self):
        import itertools
        from search_cpu import AXES
        decoded = []
        for p, lazy, index, block, tail in itertools.product(range(11), AXES['lazy'], AXES['index'], AXES['block_tokens'], [None, 2, 3, 4, 5]):
            params = {'probe_exponent': p, 'lazy': lazy, 'index': index, 'block_tokens': block, 'full_insertion': tail is None}
            if tail is not None:
                params['tail_exponent'] = tail
            decoded.append(identity(TPEProposer.decode_params(params)))
        self.assertEqual(len(set(decoded)), 880)
        optimizer, trials = TPEProposer(17), []
        for index in range(32):
            config = optimizer.ask(trials)
            key = identity(config)
            self.assertNotIn(key, {t['id'] for t in trials})
            result = {'id': key, 'config': config, 'aggregate': {'time_vs_paired_balanced': 1 + index / 100, 'packed_bytes': 10000 - index}}
            optimizer.tell(result)
            trials.append(result)
            if index == 0:
                optimizer.study.enqueue_trial(optimizer.study.trials[-1].params)
        self.assertGreaterEqual(optimizer.cached, 1)
        for trial in optimizer.study.trials:
            self.assertEqual(trial.user_attrs['config_id'], identity(TPEProposer.decode_params(trial.params)))
            self.assertEqual('tail_exponent' in trial.params, not trial.params['full_insertion'])
        optimizer.ask(trials)
        optimizer.fail()
        self.assertIsNone(optimizer.study.trials[-1].values)
        self.assertEqual(optimizer.study.trials[-1].state.name, 'FAIL')


if __name__ == "__main__":
    unittest.main()
