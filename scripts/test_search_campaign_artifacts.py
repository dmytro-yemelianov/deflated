#!/usr/bin/env python3
"""Published campaign matrix/aggregate integrity, without speed thresholds."""
import gzip
import hashlib
import json
import pathlib
import statistics
import unittest

from search_campaign import relative_summary
from search_cpu import aggregate, identity


class ArtifactTests(unittest.TestCase):
    def test_compressed_ledger_is_hash_linked_complete_and_reproduces_scores(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / "scripts/reports/search-campaign.json").read_text())
        payload = (root / report["raw_ledger"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["raw_ledger_sha256"])
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        self.assertEqual(len(rows), report["raw_rows"])
        cases = {partition: {pathlib.PurePosixPath(c["path"]).name: c
                             for c in report["corpus"]["cases"] if c["partition"] == partition}
                 for partition in ("train", "validation")}
        groups = {}
        for row in rows:
            key = row["phase"], row.get("study"), row["trial_id"]
            groups.setdefault(key, []).append(row)
            self.assertEqual(len(row["packed_sha256"]), 64)
            self.assertEqual(len(row["baseline_packed_sha256"]), 64)
            self.assertGreater(row["packed_bytes"], 0)
            self.assertGreater(row["baseline_bytes"], 0)
            for field in ("samples_ns", "baseline_samples_ns"):
                self.assertTrue(all(0 < value < float("inf") for value in row[field]))
        expected = set()
        for index, study in enumerate(report["studies"]):
            self.assertFalse(study["validation_measured"])
            self.assertEqual(len(study["training"]), study["configured_trial_budget"] + 4)
            for trial in study["training"]:
                key = "train", index, trial["id"]
                expected.add(key)
                measured = groups[key]
                self.assertEqual(identity(trial["config"]), trial["id"])
                self.assertEqual(aggregate(measured), trial["aggregate"])
                self.assertEqual(len(measured), trial["verified_streams"])
                self.check_matrix(measured, cases["train"], study["rounds"])
        for phase, measurements in (("validation", report["validation"]), ("direct", report["direct_comparisons"])):
            for measurement in measurements:
                label = phase if phase == "validation" else "direct-" + measurement["role"]
                key = label, None, measurement["id"]
                expected.add(key)
                measured = groups[key]
                self.assertEqual(relative_summary(measured, measurement["baseline"]), measurement["aggregate"])
                self.check_matrix(measured, cases["validation"], report["protocol"]["validation_rounds"])
        self.assertEqual(expected, set(groups))
        self.assertEqual({m["id"] for m in report["validation"]}, set(report["finalists"]["configs"]))
        self.assertFalse(report["test_partition_measured"])
        self.assertEqual(report["promotion"], "none")

    def check_matrix(self, rows, cases, rounds):
        self.assertEqual(len(rows), len(cases))
        self.assertEqual({r["input"] for r in rows}, set(cases))
        for row in rows:
            self.assertEqual(row["raw_bytes"], cases[row["input"]]["bytes"])
            self.assertEqual(len(row["samples_ns"]), rounds)
            self.assertEqual(len(row["baseline_samples_ns"]), rounds)

    def test_memory_samples_are_positive_and_reported_medians_are_correct(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / "scripts/reports/search-campaign.json").read_text())
        memory = report["memory"]
        validation = [c for c in report["corpus"]["cases"] if c["partition"] == "validation"]
        chosen = [max([c for c in validation if (c["family"] == "real") == real],
                      key=lambda c: (c["bytes"], c["path"]))["path"] for real in (True, False)]
        self.assertEqual(memory["cases"], chosen)
        self.assertEqual(len(memory["measurements"]), len(report["finalists"]["configs"]) * len(memory["cases"]))
        names = {pathlib.PurePosixPath(path).name for path in memory["cases"]}
        expected = {(key, name) for key in report["finalists"]["configs"] for name in names}
        self.assertEqual({(row["id"], row["input"]) for row in memory["measurements"]}, expected)
        for row in memory["measurements"]:
            samples = row["samples_rss_bytes"]
            self.assertEqual(len(samples), memory["repetitions"])
            self.assertTrue(all(value > 0 for value in samples))
            self.assertEqual(max(samples), row["peak_rss_bytes"])
            self.assertEqual(statistics.median(samples), row["median_rss_bytes"])


if __name__ == "__main__":
    unittest.main()
