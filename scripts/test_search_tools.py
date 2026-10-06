#!/usr/bin/env python3
"""Research-tool integrity gates; no performance assertions in CI."""
import copy
import collections
import hashlib
import json
import pathlib
import tempfile
import unittest
import zlib

from search_corpus import (HASH_BITS, HASH_MULTIPLIER, manifest, payload,
                           ROOT, validate)
from search_poc import CANDIDATES, check_rows, decode_exact, pareto, summarize


class IntegrityTests(unittest.TestCase):
    def test_recorded_evidence_is_complete_and_untampered(self):
        report = json.loads((ROOT / "scripts/reports/search-spikes.json").read_text())
        ledger = ROOT / report["measurement_ledger"]["path"]
        self.assertEqual(hashlib.sha256(ledger.read_bytes()).hexdigest(),
                         report["measurement_ledger"]["sha256"])
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertEqual(len(rows), report["measurement_ledger"]["rows"])
        keys = {(r["partition"], r["input"], r["candidate"]) for r in rows}
        self.assertEqual(len(keys), len(rows))
        self.assertFalse(report["reserved_test_measured"])
        self.assertFalse(any(r["partition"] == "test" for r in rows))
        for pilot in report["cpu_pilots"]:
            selected = [r for r in rows if r["partition"] == pilot["partition"]]
            self.assertEqual(len(selected), pilot["verification"]["streams"])
            counts = collections.Counter(r["candidate"] for r in selected)
            self.assertEqual(dict(counts), {c: pilot["measured_cases"] for c in CANDIDATES})
            for row in selected:
                self.assertEqual(len(row["samples_ns"]), pilot["rounds"])
                self.assertTrue(all(v > 0 for v in row["samples_ns"]))
                self.assertGreater(row["packed_bytes"], 0)

    def test_regeneration_and_split_isolation(self):
        meta, cases = manifest("smoke", 195107)
        self.assertEqual(meta, manifest("smoke", 195107)[0])
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for case, data in cases:
                file = root / case["path"]
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(data)
            validate(root, meta)
            # Detect train/validation leakage even when file hashes are right.
            leaked = copy.deepcopy(meta)
            train = next(c for c in leaked["cases"] if c["partition"] == "train")
            validation = next(c for c in leaked["cases"] if c["partition"] == "validation")
            validation["regime"] = train["regime"]
            with self.assertRaises(ValueError):
                validate(root, leaked)
            # Detect a stale extra raw file and a one-byte corruption.
            extra = root / "train/extra.raw"
            extra.write_bytes(b"extra")
            with self.assertRaises(ValueError):
                validate(root, meta)
            extra.unlink()
            first = root / cases[0][0]["path"]
            first.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                validate(root, meta)

    def test_collision_generator_hits_the_intended_hash(self):
        data = payload("hash_collision", {"keys": 128}, 71, 32768)
        buckets = {((int.from_bytes(data[i:i + 4], "little") * HASH_MULTIPLIER & 0xFFFFFFFF)
                    >> (32 - HASH_BITS)) for i in range(0, len(data), 4)}
        self.assertEqual(len(buckets), 1)
        self.assertGreater(len({data[i:i + 4] for i in range(0, len(data), 4)}), 64)

    def test_distance_and_adversarial_samples(self):
        for distance in (32767, 32768, 32769):
            data = payload("distance", {"distance": distance}, 71, 32768)
            self.assertEqual(data[:258], data[distance:distance + 258])
        for flat in (False, True):
            data = payload("sample_trap", {"flat_samples": flat, "period": 7}, 71, 32768)
            step = (len(data) - 512) // 7
            samples = [data[i * step:i * step + 512] for i in range(8)]
            if flat:
                self.assertTrue(all(len(set(s)) == 256 for s in samples))
                self.assertGreater(sum(a == b for a, b in zip(data, data[3:])), len(data) // 2)
            else:
                self.assertTrue(all(s[7:] == s[:-7] for s in samples))

    def test_mixed_generator_contains_all_three_segments_in_smoke_mode(self):
        for segment in (1024, 16384, 32768):
            data = payload("mixed", {"segment_bytes": segment}, 71, 32768)
            self.assertGreaterEqual(len(data), 3 * segment)
            chunks = [data[i * segment:(i + 1) * segment] for i in range(3)]
            self.assertTrue(any(b'"key"' in chunk for chunk in chunks))
            self.assertTrue(any(chunk[7:] == chunk[:-7] for chunk in chunks))
            self.assertTrue(any(len(set(chunk)) > 200 for chunk in chunks))

    def test_exact_decoder_rejects_truncation_trailing_bytes_and_wrong_payload(self):
        raw = b"hello" * 200
        encoder = zlib.compressobj(wbits=-15)
        packed = encoder.compress(raw) + encoder.flush()
        decode_exact(packed, raw)
        for stream, expected in [(packed[:-1], raw), (packed + b"extra", raw), (packed, b"wrong")]:
            with self.assertRaises((ValueError, zlib.error)):
                decode_exact(stream, expected)

    def test_pareto_keeps_tradeoffs_and_ties(self):
        points = [{"candidate": name, "packed_bytes": size, "encode_ns": time}
                  for name, size, time in [("fast", 100, 10), ("small", 80, 20),
                                           ("dominated", 110, 30), ("tie", 100, 10)]]
        self.assertEqual(pareto(points), ["fast", "small", "tie"])

    def test_equivalent_control_is_measured_but_not_selected(self):
        rows = [{"candidate": candidate, "raw_bytes": 200,
                 "packed_bytes": 10 if candidate in ("balanced", "split16384") else 100,
                 "samples_ns": [1 if candidate == "split16384" else 2 if candidate == "balanced" else 100]}
                for candidate in CANDIDATES]
        result = summarize(rows)
        self.assertEqual(len(result["aggregate"]), len(CANDIDATES))
        self.assertEqual(result["provisional_frontier"], ["balanced"])

    def test_matrix_rejects_duplicates_missing_rows_and_nonfinite_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            cases = [{"path": "train/input.raw", "bytes": 3}]
            rows = []
            for candidate in CANDIDATES:
                (root / candidate).mkdir()
                (root / candidate / "input.raw.deflate").write_bytes(b"stream")
                rows.append({"input": "input.raw", "candidate": candidate,
                             "raw_bytes": 3, "packed_bytes": 6, "samples_ns": [1, 2, 3]})
            check_rows(rows, cases, root, 3)
            for broken in [rows[:-1], rows + [rows[0]], json.loads(json.dumps(rows))]:
                if len(broken) == len(rows):
                    broken[0]["samples_ns"][0] = float("nan")
                with self.assertRaises(ValueError):
                    check_rows(broken, cases, root, 3)


if __name__ == "__main__":
    unittest.main()
