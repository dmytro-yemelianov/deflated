#!/usr/bin/env python3
"""Integrity gates for grouped workloads, frozen selection and RSS units."""
import hashlib
import json
import pathlib
import random
import tempfile
import unittest
from unittest import mock

from search_campaign import confidence, factorial_configs, freeze_finalists, hypervolume, relative_summary, rss_bytes
from search_cpu import AXES, identity
from search_workloads import build, validate_groups


class CampaignTests(unittest.TestCase):
    def test_direct_comparisons_name_the_actual_reference(self):
        rows = [{"raw_bytes": 100, "packed_bytes": 40, "baseline_bytes": 50,
                 "samples_ns": [2, 3, 4], "baseline_samples_ns": [4, 6, 8]}]
        result = relative_summary(rows, "miniz6")
        self.assertEqual(result["speed_vs_reference"], 2)
        self.assertEqual(result["size_vs_reference"], .8)
        self.assertNotIn("size_vs_balanced", result)

    def test_hypervolume_is_exact_for_known_union_and_rejects_invalid_points(self):
        self.assertEqual(hypervolume([(1, 1), (2, .5), (3, 1.2), (5, .1)], (4, 1.5)), 2.5)
        self.assertEqual(hypervolume([(1, 1), (1, 1)], (4, 1.5)), 1.5)
        for point in [(0, 1), (float("nan"), 1), (1, float("inf"))]:
            with self.assertRaises(ValueError):
                hypervolume([point], (4, 1.5))

    def test_factorial_covers_all_contexts_and_is_seeded(self):
        protocol = json.loads((pathlib.Path(__file__).parent / "search_protocol.json").read_text())
        configs = factorial_configs(protocol["factorial"], protocol["factorial_seed"])
        self.assertEqual(len(configs), 128)
        self.assertEqual(configs, factorial_configs(protocol["factorial"], protocol["factorial_seed"]))
        self.assertEqual(len({identity(c) for c in configs}), 128)
        for axis, levels in protocol["factorial"].items():
            for level in levels:
                self.assertEqual(sum(c[axis] == level for c in configs), len(configs) // len(levels))

    def test_rss_units_and_missing_duplicate_or_zero_values(self):
        self.assertEqual(rss_bytes("  16384000  maximum resident set size\n", "Darwin"), 16384000)
        self.assertEqual(rss_bytes("rss_kib=16000\n", "Linux"), 16384000)
        for data in ["", "rss_kib=0\n", "rss_kib=1\nrss_kib=2\n"]:
            with self.assertRaises(ValueError):
                rss_bytes(data, "Linux")

    def test_bootstrap_preserves_exact_paired_ratio_and_groups(self):
        rows = [{"input": f"{i}.raw", "packed_bytes": 90, "baseline_bytes": 100,
                 "samples_ns": [1, 2, 3], "baseline_samples_ns": [2, 4, 6]} for i in range(3)]
        cases = [{"path": f"validation/{i}.raw", "family": "periodic" if i < 2 else "real",
                  **({"source_file": "one"} if i == 2 else {})} for i in range(3)]
        result = confidence(rows, cases, 100, 19)
        self.assertEqual(result["groups"], 2)
        self.assertEqual(result["speed_multiple_95pct"], [2, 2])
        for value in result["size_delta_pct_95pct"]:
            self.assertAlmostEqual(value, -10)

    def test_training_only_selection_and_regression_controls_are_frozen(self):
        config = {a: values[0] for a, values in AXES.items()}
        key = identity(config)
        trial = {"id": key, "config": config,
                 "aggregate": {"packed_bytes": 90, "time_vs_paired_balanced": .5, "size_vs_balanced": .9}}
        study = {"strategy": "random", "seed": 1, "training": [trial],
                 "finalists": {"roles": dict.fromkeys(("speed", "size", "balanced"), key), "configs": {key: config}},
                 "validation": [{"id": "poison", "config": {}, "aggregate": {"packed_bytes": 0}}]}
        protocol = {"reference_controls": ["miniz6"], "balanced_training_size_tolerance": .01}
        frozen = freeze_finalists([study], {"studies": []}, protocol)
        self.assertEqual(set(frozen["representatives"].values()), {key})
        self.assertNotIn("poison", frozen["configs"])
        self.assertIn(identity({"reference": "miniz6"}), frozen["configs"])
        self.assertIn(identity({"preset": "stored"}), frozen["configs"])

    def test_mixed_corpus_preserves_real_groups_and_catches_slice_leakage(self):
        raw = random.Random(1951).randbytes(65536)
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            real = root / "real"
            for partition in ("train", "holdout"):
                (real / partition).mkdir(parents=True)
                (real / partition / "same.raw").write_bytes(raw)
            originals = [{"partition": p, "input": "same.raw", "bytes": len(raw), "sha256": digest, "source": "fixture"}
                         for p in ("train", "holdout")]
            (real / "manifest.json").write_text(json.dumps(originals))
            with mock.patch("search_workloads.manifest", return_value=({"generator_sha256": "fixture"}, [])):
                meta, cases = build(real, 32768)
            corpus = root / "corpus"
            for case, data in cases:
                file = corpus / case["path"]
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
                case["regime"] = case["partition"]  # hide the simpler regime/hash gate
            with self.assertRaisesRegex(ValueError, "source file crosses"):
                validate_groups(corpus, meta)


if __name__ == "__main__":
    unittest.main()
