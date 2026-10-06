#!/usr/bin/env python3
"""CPU-search correctness gates; no timing threshold or optimizer-win assertion."""
import hashlib
import json
import pathlib
import random
import tempfile
import unittest
import zlib

from search_cpu import (AXES, CONTROLS, aggregate, canonical, frontier,
                        identity, propose, select_finalists, validate_measurements,
                        worker_method)

CONFIG = {"probes": 64, "lazy": True, "insert_tail": 0, "index": "dual", "block_tokens": 16384}


class SearchTests(unittest.TestCase):
    def test_published_ledger_is_complete_hash_linked_and_reproduces_aggregates(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / "scripts/reports/search-cpu-spike.json").read_text())
        payload = (root / report["raw_ledger"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["raw_ledger_sha256"])
        rows = [json.loads(line) for line in payload.splitlines()]
        self.assertEqual(len(rows), report["raw_rows"])
        groups = {}
        for row in rows:
            self.assertIn(row["partition"], ("train", "validation"))
            key = row["run_id"], row["partition"], row["trial_id"]
            groups.setdefault(key, []).append(row)
        expected = set()
        for study in report["studies"]:
            count = 0
            for trial in study["training"] + study["validation"]:
                key = study["run_id"], trial["partition"], trial["id"]
                expected.add(key)
                measured = groups[key]
                count += len(measured)
                self.assertEqual(len(measured), trial["verified_streams"])
                self.assertEqual(len({r["input"] for r in measured}), len(measured))
                self.assertEqual(identity(trial["config"]), trial["id"])
                self.assertEqual(aggregate(measured), trial["aggregate"])
                for row in measured:
                    self.assertEqual(row["strategy"], study["strategy"])
                    self.assertEqual(len(row["packed_sha256"]), 64)
                    for field in ("samples_ns", "baseline_samples_ns"):
                        self.assertEqual(len(row[field]), study["rounds"])
                        self.assertTrue(all(0 < sample < float("inf") for sample in row[field]))
            self.assertEqual(count, study["total_verified_streams"])
            self.assertEqual({t["id"] for t in study["validation"]}, set(study["finalists"]["roles"].values()))
            self.assertFalse(study["test_partition_measured"])
        self.assertEqual(expected, set(groups))

    def test_config_identity_and_rejection_of_inactive_or_unbounded_fields(self):
        self.assertEqual(identity(CONFIG), identity(dict(reversed(list(CONFIG.items())))))
        self.assertEqual(worker_method(CONFIG), "config:64:1:0:dual:16384")
        invalid = [{**CONFIG, "probes": v} for v in [0, 1025, True, 1.5]]
        invalid += [{**CONFIG, "lazy": 1}, {**CONFIG, "insert_tail": 33},
                    {**CONFIG, "block_tokens": 255}, {**CONFIG, "index": "auto"},
                    {"preset": "balanced", **CONFIG}, {"preset": "unknown"}]
        for config in invalid:
            with self.assertRaises(ValueError):
                canonical(config)
        self.assertEqual(worker_method(CONTROLS[0]), "balanced")

    def test_proposals_are_reproducible_distinct_and_valid(self):
        for strategy in ["random", "pareto-mutation"]:
            sequences = []
            for _ in range(2):
                rng = random.Random(17)
                trials, seen, sequence = [], set(), []
                for i in range(32):
                    config = propose(rng, strategy, trials, seen)
                    key = identity(config)
                    self.assertNotIn(key, seen)
                    seen.add(key)
                    sequence.append(config)
                    self.assertTrue(all(config[a] in values for a, values in AXES.items()))
                    trials.append({"id": key, "config": config,
                                   "aggregate": {"packed_bytes": 100 - i, "time_vs_paired_balanced": 1 + i / 100}})
                sequences.append(sequence)
            self.assertEqual(*sequences)

    def test_frontier_and_finalists_preserve_tradeoffs_and_size_constraint(self):
        trials = [{"id": key, "config": {"preset": preset},
                   "aggregate": {"packed_bytes": size, "time_vs_paired_balanced": time,
                                 "size_vs_balanced": size / 100}}
                  for key, preset, size, time in [("stored", "stored", 200, .01),
                                                 ("fast", "fast", 115, .5),
                                                 ("balanced", "balanced", 100, 1),
                                                 ("best", "best", 95, 2),
                                                 ("dominated", "best", 120, 3)]]
        self.assertEqual([t["id"] for t in frontier(trials)], ["stored", "fast", "balanced", "best"])
        self.assertEqual(select_finalists(trials, .01), {"speed": "fast", "size": "best", "balanced": "balanced"})

    def test_aggregate_sums_times_instead_of_averaging_throughputs(self):
        rows = [{"raw_bytes": n, "packed_bytes": n // 2, "baseline_bytes": n,
                 "samples_ns": [ns, ns, ns], "baseline_samples_ns": [ns * 2] * 3}
                for n, ns in [(100, 10), (900, 900)]]
        result = aggregate(rows)
        self.assertAlmostEqual(result["mb_s"], 1000 / 910 * 1e3)
        self.assertEqual(result["time_vs_paired_balanced"], .5)
        self.assertEqual(result["size_vs_balanced"], .5)

    def test_measurement_gate_rejects_incomplete_corrupt_or_nonfinite_results(self):
        raw = b"test" * 100
        encoder = zlib.compressobj(wbits=-15)
        packed = encoder.compress(raw) + encoder.flush()
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / "train").mkdir()
            (root / "train/input.raw").write_bytes(raw)
            streams = root / "streams"
            streams.mkdir()
            (streams / "input.raw.deflate").write_bytes(packed)
            case = {"path": "train/input.raw", "bytes": len(raw)}
            row = {"input": "input.raw", "raw_bytes": len(raw), "packed_bytes": len(packed),
                   "baseline_bytes": len(packed), "samples_ns": [1, 2, 3], "baseline_samples_ns": [1, 2, 3]}
            validate_measurements([row], [case], streams, 3, root)
            for rows in [[], [row, row], [{**row, "samples_ns": [float("nan"), 2, 3]}]]:
                with self.assertRaises(ValueError):
                    validate_measurements(rows, [case], streams, 3, root)
            (streams / "input.raw.deflate").write_bytes(packed[:-1])
            with self.assertRaises(ValueError):
                validate_measurements([row], [case], streams, 3, root)


if __name__ == "__main__":
    unittest.main()
