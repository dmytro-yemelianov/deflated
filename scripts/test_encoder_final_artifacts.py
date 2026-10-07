#!/usr/bin/env python3
"""Audit published P5 provenance, complete observations and qualification."""
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import unittest

from encoder_final_stats import role_guards, rss_increase, validate_rows
from search_final_campaign import parse_rss, schedule
from search_final_stats import direct, summary

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "scripts/reports"


def digest(data):
    return hashlib.sha256(data).hexdigest()


class FinalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads((REPORTS / "encoder-p5-final-receipt.json").read_text())
        cls.payloads = {}
        for name, expected in cls.receipt["files"].items():
            packed = (REPORTS / name).read_bytes()
            if digest(packed) != expected["sha256"]:
                raise ValueError("published artifact changed: " + name)
            raw = gzip.decompress(packed) if name.endswith(".gz") else packed
            if digest(raw) != expected["uncompressed_sha256"]:
                raise ValueError("published uncompressed artifact changed: " + name)
            cls.payloads[name] = raw
        cls.freeze = json.loads(cls.payloads["encoder-p5-freeze.json"])
        cls.manifest = json.loads(cls.payloads["encoder-p5-manifest.json"])
        cls.result = json.loads(cls.payloads["encoder-p5-result.json"])
        cls.stats = json.loads(cls.payloads["encoder-p5-statistics.json.gz"])
        cls.rss = json.loads(cls.payloads["encoder-p5-rss.json.gz"])
        cls.model = json.loads(cls.payloads["encoder-p5-correspondence.json.gz"])
        cls.prototype = json.loads(cls.payloads["encoder-prototype-correspondence.json.gz"])
        cls.rows = [json.loads(line) for line in cls.payloads["encoder-p5-measurements.jsonl.gz"].splitlines()]

    def assert_metrics(self, actual, expected):
        if isinstance(expected, float):
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12))
        elif isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key in expected:
                self.assert_metrics(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                self.assert_metrics(left, right)
        else:
            self.assertEqual(actual, expected)

    def test_freeze_and_completed_hash_chain(self):
        self.assertFalse(self.freeze["held_encoded_before_freeze"])
        self.assertFalse(self.freeze["held_features_before_freeze"])
        self.assertFalse(self.result["adaptive_test_feedback"])
        self.assertEqual(self.freeze["contract"], json.loads((ROOT / "scripts/encoder_protocol.json").read_text()))
        self.assertEqual(digest(self.payloads["encoder-p5-manifest.json"]), self.freeze["artifacts"]["manifest.json"])
        self.assertEqual(digest(self.payloads["encoder-p5-freeze.json"]), self.result["freeze_sha256"])
        self.assertEqual(digest(self.payloads["encoder-p5-measurements.jsonl.gz"]), self.result["measurement_sha256"])
        self.assertEqual(digest(self.payloads["encoder-p5-rss.json.gz"]), self.result["rss_sha256"])
        self.assertEqual(digest(self.payloads["encoder-p5-result.json"]), self.stats["result_sha256"])
        self.assertEqual(self.stats["freeze_sha256"], self.result["freeze_sha256"])
        self.assertEqual(self.model["freeze_sha256"], self.result["freeze_sha256"])
        self.assertEqual(self.model["checker_sha256"], self.freeze["source_sha256"]["scripts/encoder_final_correspondence.py"])

    def test_complete_rotated_matrix_and_packet_identity(self):
        cases = self.manifest["cases"]
        methods = self.freeze["methods"]
        sessions = self.freeze["contract"]["measurement"]["sessions"]
        validate_rows(self.rows, cases, methods, sessions)
        self.assertEqual(len(self.rows), self.result["verified_rows"])
        self.assertEqual(len(self.rows), 8700)
        groups = defaultdict(list)
        for row in self.rows:
            case = cases[row["original_case_index"]]
            self.assertEqual(case["path"], row["input"])
            self.assertEqual(case["bytes"], row["raw_bytes"])
            self.assertEqual(case["scope"], row["scope"])
            self.assertEqual(case["family"], row["family"])
            ordered = schedule(row["session"], row["original_case_index"], list(methods))
            self.assertEqual(ordered[row["method_order"]], (row["method"], row["pair_order"]))
            groups[row["method"], row["input"]].append(row)
            if row["method"] == "core-reversal":
                self.assertEqual(row["packet_sha256"], row["baseline_packet_sha256"])
        for observations in groups.values():
            self.assertEqual(len({r["method_order"] for r in observations}), sessions)
            self.assertEqual(sum(r["pair_order"] == 0 for r in observations), sessions // 2)
        case_by_path = {c["path"]: c for c in cases}
        expected_rss = self.freeze["rss_cases"]
        self.assertEqual({case_by_path[p]["class"] for p in expected_rss if case_by_path[p]["scope"] == "new-real-test"},
                         {c["class"] for c in cases if c["scope"] == "new-real-test"})

    def test_role_summaries_guards_and_frontier(self):
        protocol = self.freeze["contract"]
        measurement = protocol["measurement"]
        for role, spec in protocol["roles"].items():
            value = self.stats["roles"][role]
            self.assertEqual(value["baseline"], "original " + spec["baseline"])
            subset = [r for r in self.rows if r["method"] == value["method"]]
            for scope, metric in value["metrics"].items():
                self.assert_metrics(summary([r for r in subset if r["scope"] == scope], measurement["seed"], measurement["bootstrap_repetitions"]), metric)
            memory = rss_increase(self.rss, value["method"])
            self.assertEqual(memory, value["rss"])
            self.assertEqual(role_guards(value["metrics"], spec, protocol["common_guards"], memory,
                                        self.stats["portable_size"]["binary_growth_bytes"]), value["guardrails"])
            controls = self.stats["controls_by_role"][role]
            eligible = [name for name in protocol["controls"] if controls[name]["guardrails"]["passed"]]
            self.assertEqual(value["frontier"]["guard_qualifying_controls"], eligible)
            current = value["metrics"]["new-real-test"]
            dominated = [name for name in eligible if controls[name]["metrics"]["new-real-test"]["packed_bytes"] <= current["packed_bytes"]
                         and controls[name]["metrics"]["new-real-test"]["summed_file_medians_ns"]["encode_ns"] <= current["summed_file_medians_ns"]["encode_ns"]]
            self.assertEqual(value["frontier"]["dominated_by"], dominated)
            self.assertEqual(value["frontier"]["new_point"], value["guardrails"]["passed"] and not dominated)

    def test_controls_references_and_family_metrics(self):
        protocol = self.freeze["contract"]
        m = protocol["measurement"]
        grouped = {name: [r for r in self.rows if r["method"] == name] for name in self.freeze["methods"]}
        for name, scopes in self.stats["all_methods"].items():
            for scope, metric in scopes.items():
                self.assert_metrics(summary([r for r in grouped[name] if r["scope"] == scope], m["seed"], m["bootstrap_repetitions"]), metric)
        for role, controls in self.stats["controls_by_role"].items():
            spec = protocol["roles"][role]
            self.assertEqual(set(controls), set(protocol["controls"]))
            for name, control in controls.items():
                if spec["baseline"] == "balanced":
                    expected = self.stats["all_methods"][name]
                else:
                    expected = {}
                    for scope in control["metrics"]:
                        metric = direct([r for r in grouped[name] if r["scope"] == scope],
                                        [r for r in grouped["best"] if r["scope"] == scope], m["seed"], m["bootstrap_repetitions"])
                        for key in tuple(metric):
                            if key.endswith("_vs_reference"):
                                metric[key.replace("_vs_reference", "_vs_balanced")] = metric.pop(key)
                        for f in metric["per_file"].values():
                            f["warm_baseline_encode_ns"] = f.pop("warm_reference_encode_ns")
                        expected[scope] = metric
                self.assert_metrics(expected, control["metrics"])
                memory = rss_increase(self.rss, name, spec["baseline"])
                self.assertEqual(memory, control["rss"])
                self.assertEqual(role_guards(expected, spec, protocol["common_guards"], memory, 0), control["guardrails"])
        for name, references in self.stats["direct_references"].items():
            for reference, scopes in references.items():
                for scope, metric in scopes.items():
                    self.assert_metrics(direct([r for r in grouped[name] if r["scope"] == scope],
                                               [r for r in grouped[reference] if r["scope"] == scope], m["seed"], m["bootstrap_repetitions"]), metric)
        for name, scopes in self.stats["per_family"].items():
            for scope, families in scopes.items():
                for family, metric in families.items():
                    self.assert_metrics(summary([r for r in grouped[name] if r["scope"] == scope and r["family"] == family], m["seed"], m["bootstrap_repetitions"]), metric)

    def test_rss_and_timed_model_packets(self):
        platform = "Darwin" if "macOS" in self.result["platform"] else "Linux"
        self.assertEqual(len(self.rss), self.result["rss_processes"])
        rss_keys = set()
        methods = self.freeze["methods"]
        wanted = {(path, name, side, repeat) for path in self.freeze["rss_cases"] for name, method in methods.items()
                  for side in (("candidate",) if method["origin"] == "original control" else ("candidate", "baseline"))
                  for repeat in range(3)}
        timed = {(r["method"], r["input"]): r for r in self.rows}
        for record in self.rss:
            self.assertEqual(parse_rss(record["stderr"], platform), record["peak_rss_bytes"])
            key = record["input"], record["method"], record["side"], record["repeat"]
            self.assertNotIn(key, rss_keys)
            rss_keys.add(key)
            measured = timed[record["method"], record["input"]]
            self.assertEqual(record["packet_sha256"], measured["packet_sha256" if record["side"] == "candidate" else "baseline_packet_sha256"])
        self.assertEqual(rss_keys, wanted)
        model = {(r["method"], r["input"]): r for r in self.model["records"]}
        methods = ("new-speed", "new-compromise", "new-size", "core-reversal")
        self.assertEqual(set(model), {(m, c["path"]) for m in methods for c in self.manifest["cases"]})
        self.assertEqual(self.model["packets"], len(model))
        self.assertEqual(len(model), 232)
        cases = {c["path"]: c for c in self.manifest["cases"]}
        for key, record in model.items():
            self.assertEqual(record["packet_sha256"], timed[key]["packet_sha256"])
            self.assertEqual(record["raw_sha256"], cases[record["input"]]["sha256"])
            self.assertEqual(record["lean_decoded_sha256"], record["raw_sha256"])
            self.assertEqual(record["rust_decoded_sha256"], record["raw_sha256"])

    def test_default_core_supplementary_gate(self):
        value = self.stats["default_core"]
        measurement = self.freeze["contract"]["measurement"]
        subset = [r for r in self.rows if r["method"] == "core-reversal"]
        for scope, metric in value["metrics"].items():
            self.assert_metrics(summary([r for r in subset if r["scope"] == scope], measurement["seed"], measurement["bootstrap_repetitions"]), metric)
        self.assertEqual(rss_increase(self.rss, "core-reversal"), value["rss"])
        primary = value["metrics"]["new-real-test"]["session_bootstrap_95pct"]
        self.assertEqual(value["checks"]["primary_warm_improvement"], primary["warm_speed"][0] > 1)
        self.assertEqual(value["checks"]["primary_first_call_improvement"], primary["cold_speed"][0] > 1)
        self.assertEqual(value["passed"], all(value["checks"].values()))

    def test_rejected_prototype_correspondence_witnesses(self):
        value = self.prototype
        witness_path = REPORTS / "encoder-p3-train-oracle.json.gz"
        self.assertEqual(digest(witness_path.read_bytes()), value["p3_witness_sha256"])
        self.assertEqual(digest((ROOT / "scripts/encoder_prototype_correspondence.py").read_bytes()), value["checker_sha256"])
        self.assertEqual(value["lean_binary_sha256"], self.model["lean_binary_sha256"])
        self.assertEqual(value["rust_binary_sha256"], self.model["rust_binary_sha256"])
        witnesses = json.loads(gzip.decompress(witness_path.read_bytes()))
        expected = {(w["id"], w["method"], form): (digest(bytes.fromhex(w[key])), digest(bytes.fromhex(w["raw_hex"])))
                    for w in witnesses for form, key in (("fixed", "fixed_hex"), ("auto", "packet_hex"))}
        p3 = [r for r in value["records"] if r["study"] == "P3"]
        self.assertEqual(len(p3), 6144)
        self.assertEqual({(r["id"], r["method"], r["form"]): (r["packet_sha256"], r["raw_sha256"]) for r in p3}, expected)
        stream = json.loads((REPORTS / "encoder-p4-stream.json").read_text())
        self.assertEqual(value["p4_diagnostics_sha256"], stream["diagnostics_sha256"])
        self.assertEqual(value["p4_binary_sha256"], stream["protocol"]["frozen"]["binary_sha256"])
        p4 = [r for r in value["records"] if r["study"] == "P4"]
        self.assertEqual(len(p4), 21)
        cases = {c["raw_path"]: c for c in stream["protocol"]["cases"]}
        diagnostics = json.loads(gzip.decompress((REPORTS / "encoder-p4-stream-diagnostics.json.gz").read_bytes()))
        self.assertEqual({(r["input"], r["method"]): (r["packet_sha256"], r["raw_sha256"]) for r in p4},
                         {(cases[r["input"]]["path"], r["method"]): (r["packet_sha256"], cases[r["input"]]["sha256"]) for r in diagnostics})
        self.assertTrue(any(r["structural_counts"]["stored_blocks"] > 0 and r["structural_counts"]["matches_after_stored"] > 0 for r in p4))
        self.assertEqual(value["packets"], 6165)
        for record in value["records"]:
            self.assertEqual(record["lean_decoded_sha256"], record["raw_sha256"])
            self.assertEqual(record["rust_decoded_sha256"], record["raw_sha256"])


if __name__ == "__main__":
    unittest.main()
