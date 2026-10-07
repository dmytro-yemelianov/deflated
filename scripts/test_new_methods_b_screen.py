#!/usr/bin/env python3
"""Ensure training selection cannot exchange per-file damage for aggregate wins."""
import unittest

from new_methods_b_screen import guard_summary, summarize


def rows_for(method, packed, encode=1000, decode=1000):
    return [{"method": method, "case": f"{scope}{i}", "scope": scope, "packed_bytes": packed,
             "warm_encode_ns": encode, "first_encode_ns": encode,
             "warm_decode_ns": decode, "first_decode_ns": decode}
            for scope, count in (("primary", 8), ("tiny", 12)) for i in range(count)]


class SelectionGuards(unittest.TestCase):
    def setUp(self):
        self.good = "dsc1:16/keys/off:frame"
        self.fast = "dsc1:18/all-quoted/checked-delta:frame"
        self.controls = rows_for("zstd:3:frame", 100) + rows_for("dsc1:16/off/off:plain", 100) + rows_for("dsc1:18/off/off:plain", 100)
        self.methods = [{"id": m, "role": "candidate"} for m in (self.good, self.fast)]

    def test_worst_file_guard_rejects_fast_aggregate_winner(self):
        rows = self.controls + rows_for(self.good, 92) + rows_for(self.fast, 80, encode=10)
        next(r for r in rows if r["method"] == self.fast and r["case"] == "primary0")["packed_bytes"] = 120
        self.assertLess(guard_summary(rows, self.fast)["packed_ratio_vs_zstd3"], .95)
        self.assertEqual(summarize(rows, self.methods)["sentinel"], self.good)

    def test_slow_and_tiny_failure_cannot_qualify(self):
        rows = self.controls + rows_for(self.good, 92, encode=5000) + rows_for(self.fast, 90)
        next(r for r in rows if r["method"] == self.fast and r["case"] == "tiny0")["first_decode_ns"] = 2001
        summary = summarize(rows, self.methods)
        self.assertIsNone(summary["sentinel"])
        self.assertFalse(any(c["size_role_training_point_guards"] for c in summary["candidates"]))


if __name__ == "__main__":
    unittest.main()
