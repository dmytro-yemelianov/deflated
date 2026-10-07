#!/usr/bin/env python3
"""Optional NSGA-II adapter checks; run in the pinned research environment."""
import unittest

from search_cpu import identity
from search_optimizer import NSGAProposer


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


if __name__ == "__main__":
    unittest.main()
