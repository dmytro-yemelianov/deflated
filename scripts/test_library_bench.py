#!/usr/bin/env python3
"""Guard diagnostic aggregation: medians first, then total bytes / total time."""
import unittest
import hashlib
import tempfile
import gzip
import json
import zlib
from pathlib import Path
from library_bench import summarize, manifest_corpus, verify_freeze
from library_real_corpus import checked_blob, selected_sources, SOURCE_IDS


class SummaryTest(unittest.TestCase):
    def test_pooled_speed_is_not_mean_of_file_speeds_or_samples(self):
        rows = []
        for case, size, times in [("small", 10, [1, 3, 1000]), ("big", 100, [10, 20, 30])]:
            for duration in times:
                rows.append(dict(case=case, raw_bytes=size, decode_ns=duration,
                                 scope="repository", frame="raw", encoder="zlib", method="core"))
        # A separate synthetic case must not contaminate the repository scope.
        rows.append(dict(case="noise", raw_bytes=999, decode_ns=1,
                         scope="synthetic", frame="raw", encoder="zlib", method="core"))
        result = summarize(rows)
        repository = next(r for r in result if r["scope"] == "repository")
        self.assertEqual(repository["summed_median_ns"], 23)
        self.assertAlmostEqual(repository["MB_per_s"], 110 * 1000 / 23)


    def test_mixed_contexts_cannot_be_pooled(self):
        base = dict(case="small", raw_bytes=10, decode_ns=5, scope="repository",
                    frame="raw", encoder="zlib", method="core")
        with self.assertRaisesRegex(ValueError, "context"):
            summarize([dict(base, context="fresh-decoder-only"),
                       dict(base, context="reuse-state-output")])

    def test_manifest_rejects_tampering_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = b"payload"
            (root / "data").write_bytes(data)
            case = {"name": "case-1", "path": "data", "scope": "synthetic",
                    "sha256": hashlib.sha256(data).hexdigest()}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"cases": [case]}))
            self.assertEqual(next(manifest_corpus(manifest))[2], data)
            (root / "data").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash"):
                list(manifest_corpus(manifest))
            (root / "data").write_bytes(data)
            manifest.write_text(json.dumps({"cases": [case, case]}))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                list(manifest_corpus(manifest))

    def test_source_snapshots_match_original_receipts(self):
        reports = Path(__file__).parent / "reports"
        for version in ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10"]:
            receipt = json.loads(gzip.decompress((reports / f"library-decode-{version}.json.gz").read_bytes()))
            snapshot = json.loads(gzip.decompress((reports / f"library-decode-{version}-core-sources.json.gz").read_bytes()))
            for name, source in snapshot["files"].items():
                self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), receipt["source_sha256"][name])

    def test_freeze_rejects_binary_source_and_missing_source_changes(self):
        sources = {"core.rs": "source-digest"}
        freeze = {"sources": sources, "binary_sha256": "binary-digest"}
        verify_freeze(freeze, sources, "binary-digest")
        for changed, binary in [(sources, "other"), ({"core.rs": "other"}, "binary-digest"),
                                ({}, "binary-digest")]:
            with self.assertRaisesRegex(ValueError, "frozen"):
                verify_freeze(freeze, changed, binary)

    def test_real_sources_are_pinned_training_data_and_downloads_are_checked(self):
        sources = selected_sources()
        self.assertEqual(tuple(s["id"] for s in sources), SOURCE_IDS)
        for source in sources:
            self.assertEqual(source["partition"], "train")
            self.assertIn(source["pinned_commit"], source["url"])
            self.assertIn(source["pinned_commit"], source["license_url"])
        data = b"real file"
        digest = hashlib.sha1(b"blob 9\0" + data).hexdigest()
        self.assertEqual(checked_blob(data, digest), data)
        with self.assertRaisesRegex(ValueError, "Git blob"):
            checked_blob(data + b"!", digest)

    def test_published_receipt_recomputes_and_has_complete_pairs(self):
        path = Path(__file__).parent / "reports/library-decode-v1.json.gz"
        report = json.loads(gzip.decompress(path.read_bytes()))
        rows = report["rows"]
        self.assertEqual(summarize(rows), report["summary"])
        self.assertEqual(len(rows), 840)
        self.assertEqual(report["rejection_contracts"], 588)
        seen = set()
        packets = {}
        for row in rows:
            key = (row["case"], row["frame"], row["encoder"])
            digest = (row["raw_sha256"], row["packet_sha256"])
            self.assertEqual(packets.setdefault(key, digest), digest)
            sample_key = (row["session"], row["method"], key)
            self.assertNotIn(sample_key, seen)
            seen.add(sample_key)
            self.assertGreater(row["decode_ns"], 0)
            self.assertGreaterEqual(row["decode_ns"] * row["decode_iterations"], report["minimum_ns"] * .999)
        self.assertEqual(len(packets), 42)
        self.assertEqual(len(seen), report["sessions"] * len(report["methods"]) * len(packets))


    def test_v2_receipts_bind_baseline_freeze_and_complete_pairs(self):
        self.check_receipts("v1", [
            ("library-decode-v2", 840, 42, 588),
            ("library-decode-v2-expanded", 1152, 96, 1344),
        ])

    def test_v3_receipts_bind_baseline_freeze_and_complete_pairs(self):
        self.check_receipts("v2", [
            ("library-decode-v3", 840, 42, 588),
            ("library-decode-v3-real", 2160, 108, 1512),
            ("library-decode-v3-expanded", 1152, 96, 1344),
        ])

    def test_v4_receipts_bind_baseline_freeze_and_complete_pairs(self):
        self.check_receipts("v3", [
            ("library-decode-v4", 840, 42, 588),
            ("library-decode-v4-real", 2160, 108, 1512),
            ("library-decode-v4-expanded", 1152, 96, 1344),
            ("library-decode-v4-window-followup", 336, 12, 168),
        ])

    def test_v5_fresh_and_reuse_receipts_are_separate_and_paired(self):
        self.check_receipts("v4", [
            ("library-decode-v5", 840, 42, 588),
            ("library-decode-v5-real", 2160, 108, 1512),
        ])
        self.check_receipts(None, [
            ("library-decode-v5-reuse", 630, 42, 441),
            ("library-decode-v5-reuse-real", 1620, 108, 1134),
        ])
        reports = Path(__file__).parent / "reports"
        for suffix in ["", "-real"]:
            fresh = json.loads(gzip.decompress((reports / f"library-decode-v5{suffix}.json.gz").read_bytes()))
            reuse = json.loads(gzip.decompress((reports / f"library-decode-v5-reuse{suffix}.json.gz").read_bytes()))
            self.assertEqual(fresh["source_sha256"], reuse["source_sha256"])
            self.assertEqual(fresh["native_build"], reuse["native_build"])
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["raw_sha256"], r["packet_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            for report, context in [(fresh, "fresh-decoder-only"), (reuse, "reuse-state-output")]:
                self.assertEqual(report["context"], context)
                self.assertEqual({r["context"] for r in report["rows"]}, {context})

    def test_v6_receipts_include_packed_module_and_matching_context_baselines(self):
        self.check_receipts("v5", [
            ("library-decode-v6", 840, 42, 588),
            ("library-decode-v6-real", 2160, 108, 1512),
        ])
        self.check_receipts("v5-reuse", [
            ("library-decode-v6-reuse", 840, 42, 588),
            ("library-decode-v6-reuse-real", 2160, 108, 1512),
            ("library-decode-v6-expanded", 1728, 144, 2016),
        ])
        reports = Path(__file__).parent / "reports"
        for suffix in ["", "-real"]:
            fresh = json.loads(gzip.decompress((reports / f"library-decode-v6{suffix}.json.gz").read_bytes()))
            reuse = json.loads(gzip.decompress((reports / f"library-decode-v6-reuse{suffix}.json.gz").read_bytes()))
            self.assertIn("crates/deflate-core/src/decode_table.rs", fresh["source_sha256"])
            self.assertEqual(fresh["source_sha256"], reuse["source_sha256"])
            self.assertEqual(fresh["native_build"], reuse["native_build"])
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["packet_sha256"], r["raw_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            self.assertEqual(fresh["context"], "fresh-decoder-only")
            self.assertEqual(reuse["context"], "reuse-state-output")

    def test_v7_receipts_bind_v6_baselines_and_identical_sources(self):
        self.check_receipts("v6", [
            ("library-decode-v7", 840, 42, 588),
            ("library-decode-v7-real", 2160, 108, 1512),
        ])
        self.check_receipts("v6-reuse", [
            ("library-decode-v7-reuse", 840, 42, 588),
            ("library-decode-v7-reuse-real", 2160, 108, 1512),
            ("library-decode-v7-expanded", 1728, 144, 2016),
        ])
        reports = Path(__file__).parent / "reports"
        candidates = [json.loads(gzip.decompress(
            (reports / f"library-decode-v7{suffix}.json.gz").read_bytes()))
            for suffix in ["", "-real", "-reuse", "-reuse-real", "-expanded"]]
        for report in candidates:
            self.assertEqual(report["source_sha256"], candidates[0]["source_sha256"])
            self.assertEqual(report["native_build"], candidates[0]["native_build"])
        for fresh, reuse in [(candidates[0], candidates[2]), (candidates[1], candidates[3])]:
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["packet_sha256"], r["raw_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            self.assertEqual(fresh["context"], "fresh-decoder-only")
            self.assertEqual(reuse["context"], "reuse-state-output")

    def test_v8_receipts_bind_v7_baselines_and_identical_sources(self):
        self.check_receipts("v7", [
            ("library-decode-v8", 840, 42, 588),
            ("library-decode-v8-real", 2160, 108, 1512),
        ])
        self.check_receipts("v7-reuse", [
            ("library-decode-v8-reuse", 840, 42, 588),
            ("library-decode-v8-reuse-real", 2160, 108, 1512),
            ("library-decode-v8-expanded", 1728, 144, 2016),
        ])
        reports = Path(__file__).parent / "reports"
        candidates = [json.loads(gzip.decompress(
            (reports / f"library-decode-v8{suffix}.json.gz").read_bytes()))
            for suffix in ["", "-real", "-reuse", "-reuse-real", "-expanded"]]
        for report in candidates:
            self.assertEqual(report["source_sha256"], candidates[0]["source_sha256"])
            self.assertEqual(report["native_build"], candidates[0]["native_build"])
        for fresh, reuse in [(candidates[0], candidates[2]), (candidates[1], candidates[3])]:
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["packet_sha256"], r["raw_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            self.assertEqual(fresh["context"], "fresh-decoder-only")
            self.assertEqual(reuse["context"], "reuse-state-output")

    def test_v9_receipts_bind_v8_baselines_and_identical_sources(self):
        self.check_receipts("v8", [
            ("library-decode-v9", 840, 42, 588),
            ("library-decode-v9-real", 2160, 108, 1512),
        ])
        self.check_receipts("v8-reuse", [
            ("library-decode-v9-reuse", 840, 42, 588),
            ("library-decode-v9-reuse-real", 2160, 108, 1512),
            ("library-decode-v9-expanded", 1728, 144, 2016),
        ])
        reports = Path(__file__).parent / "reports"
        candidates = [json.loads(gzip.decompress(
            (reports / f"library-decode-v9{suffix}.json.gz").read_bytes()))
            for suffix in ["", "-real", "-reuse", "-reuse-real", "-expanded"]]
        for report in candidates:
            self.assertEqual(report["source_sha256"], candidates[0]["source_sha256"])
            self.assertEqual(report["native_build"], candidates[0]["native_build"])
        for fresh, reuse in [(candidates[0], candidates[2]), (candidates[1], candidates[3])]:
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["packet_sha256"], r["raw_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            self.assertEqual(fresh["context"], "fresh-decoder-only")
            self.assertEqual(reuse["context"], "reuse-state-output")

    def test_v10_receipts_bind_v9_baselines_and_identical_sources(self):
        self.check_receipts("v9", [
            ("library-decode-v10", 840, 42, 588),
            ("library-decode-v10-real", 2160, 108, 1512),
        ])
        self.check_receipts("v9-reuse", [
            ("library-decode-v10-reuse", 840, 42, 588),
            ("library-decode-v10-reuse-real", 2160, 108, 1512),
            ("library-decode-v10-expanded", 1728, 144, 2016),
        ])
        reports = Path(__file__).parent / "reports"
        candidates = [json.loads(gzip.decompress(
            (reports / f"library-decode-v10{suffix}.json.gz").read_bytes()))
            for suffix in ["", "-real", "-reuse", "-reuse-real", "-expanded"]]
        for report in candidates:
            self.assertEqual(report["source_sha256"], candidates[0]["source_sha256"])
            self.assertEqual(report["native_build"], candidates[0]["native_build"])
        for fresh, reuse in [(candidates[0], candidates[2]), (candidates[1], candidates[3])]:
            def packets(report):
                return {(r["case"], r["frame"], r["encoder"], r["packet_sha256"], r["raw_sha256"])
                        for r in report["rows"]}
            self.assertEqual(packets(fresh), packets(reuse))
            self.assertEqual(fresh["context"], "fresh-decoder-only")
            self.assertEqual(reuse["context"], "reuse-state-output")

    def test_v10_header_receipts_match_frozen_workers_and_valid_packets(self):
        reports = Path(__file__).parent / "reports"
        for mode, suffix, context in [("fresh", "", "fresh-decoder-only"),
                                      ("reuse", "-reuse", "reuse-state-output")]:
            base_path = reports / f"library-decode-v10{suffix}.json.gz"
            base = json.loads(gzip.decompress(base_path.read_bytes()))
            report = json.loads(gzip.decompress(
                (reports / f"library-decode-v10-headers-{mode}.json.gz").read_bytes()))
            for key in ["source_sha256", "candidate_freeze", "native_build", "methods"]:
                self.assertEqual(report[key], base[key])
            self.assertEqual(report["context"], context)
            self.assertEqual(hashlib.sha256(report["controller_source"].encode()).hexdigest(),
                             report["controller_sha256"])
            self.assertEqual(len(report["packets"]), 24)
            self.assertEqual(len(report["rows"]), 480)
            self.assertEqual(len(report["header_contracts"]), 32)
            for check in report["header_contracts"]:
                self.assertEqual(check["exit_code"], 0 if check["method"] == "libdeflate" else 2)
            for packet in report["packets"]:
                data = bytes.fromhex(packet["packet_hex"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), packet["packet_sha256"])
                decoder = zlib.decompressobj(31)
                self.assertEqual(decoder.decompress(data) + decoder.flush(), bytes.fromhex(packet["raw_hex"]))
                self.assertTrue(decoder.eof)
                self.assertFalse(decoder.unused_data)
            keys = {(r["case"], r["method"], r["session"]) for r in report["rows"]}
            self.assertEqual(len(keys), 480)
            for row in report["rows"]:
                self.assertEqual(row["context"], context)
                self.assertGreater(row["decode_ns"], 0)
                self.assertGreaterEqual(row["decode_ns"] * row["decode_iterations"],
                                        report["minimum_ns"] * .999)
            import statistics
            for row in report["summary"]:
                for method, value in row["ns"].items():
                    self.assertEqual(value, statistics.median(r["decode_ns"] for r in report["rows"]
                        if r["case"] == row["case"] and r["method"] == method))

    def check_receipts(self, previous_version, expected):
        reports = Path(__file__).parent / "reports"
        previous = None if previous_version is None else json.loads(gzip.decompress(
            (reports / f"library-decode-{previous_version}.json.gz").read_bytes()))
        for name, count, packets, rejects in expected:
            report = json.loads(gzip.decompress((reports / (name + ".json.gz")).read_bytes()))
            if previous is None:
                self.assertNotIn("baseline", report["methods"])
                self.assertIsNone(report["baseline_receipt"])
            else:
                self.assertEqual(report["methods"]["baseline"]["sha256"], previous["methods"]["candidate"]["sha256"])
            self.assertEqual(report["candidate_freeze"]["binary_sha256"], report["methods"]["candidate"]["sha256"])
            for path, digest in report["candidate_freeze"]["sources"].items():
                self.assertEqual(report["source_sha256"][path], digest)
            rows = report["rows"]
            self.assertEqual(len(rows), count)
            self.assertEqual(summarize(rows), report["summary"])
            self.assertEqual(report["rejection_contracts"], rejects)
            keys = {(r["case"], r["frame"], r["encoder"]) for r in rows}
            self.assertEqual(len(keys), packets)
            samples = {(r["session"], r["method"], r["case"], r["frame"], r["encoder"]) for r in rows}
            self.assertEqual(len(samples), count)
            self.assertEqual(count, report["sessions"] * len(report["methods"]) * packets)
            identities = {}
            for row in rows:
                key = (row["case"], row["frame"], row["encoder"])
                digest = (row["raw_sha256"], row["packet_sha256"])
                self.assertEqual(identities.setdefault(key, digest), digest)
                self.assertGreaterEqual(row["decode_ns"] * row["decode_iterations"], report["minimum_ns"] * .999)
            if report["corpus_manifest"]:
                expected = {c["name"]: c["sha256"] for c in report["corpus_manifest"]["cases"]}
                for row in rows:
                    self.assertEqual(row["raw_sha256"], expected[row["case"]])


if __name__ == "__main__":
    unittest.main()
