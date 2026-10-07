#!/usr/bin/env python3
"""Verify actual hash collisions and raw-byte stress, without held encoding."""
import unittest

from new_methods_synthetic import FAMILIES, REGIMES, payload, recipes


class SyntheticConstruction(unittest.TestCase):
    def test_collision_rows_use_production_hash(self):
        for family, width, endian, multiplier in [("hash_trigram", 3, "big", 0x9e3779b1),
                                                   ("hash_fourbyte", 4, "little", 0x1e35a7bd),
                                                   ("cache_eviction", 3, "big", 0x9e3779b1)]:
            raw, evidence = payload(family, 13, 1871, 65536)
            row_width = width + 27 + 13
            for offset in range(0, len(raw) - row_width + 1, row_width):
                key = int.from_bytes(raw[offset:offset + width], endian)
                bucket = ((key * multiplier) & 0xffffffff) >> 17
                self.assertEqual(bucket, evidence["bucket"])

    def test_fourth_byte_guard_and_numeric_bytes(self):
        raw, evidence = payload("tag24_fourth", 13, 97, 65536)
        prefix = bytes.fromhex(evidence["shared_trigram_hex"])
        width = 4 + 20 + 13
        fourth = set()
        for offset in range(0, len(raw) - width + 1, width):
            self.assertEqual(raw[offset:offset + 3], prefix)
            fourth.add(raw[offset + 3])
        self.assertGreater(len(fourth), 8)
        numeric, _ = payload("numeric_spellings", 13, 97, 65536)
        for spelling in (b'"spelling":-0', b'"spelling":00', b'"spelling":1E+03',
                         b'"spelling":18446744073709551616'):
            self.assertIn(spelling, numeric)
        escaped, _ = payload("escaped_raw", 13, 97, 65536)
        self.assertIn(b"\xff", escaped)
        self.assertIn(b'\\u0061', escaped)

    def test_sizes_disjoint_regimes_and_chunk_cut(self):
        self.assertEqual(set(sum(REGIMES.values(), [])), set(range(13, 19)))
        for family in FAMILIES:
            raw, _ = payload(family, 13, 97, 262144)
            self.assertEqual(len(raw), 262144, family)
        raw, evidence = payload("chunk_lexemes", 13, 97)
        for cut, start, width in evidence["lexemes_cross_chunk_cuts"]:
            if cut < len(raw):
                self.assertLess(start, cut)
                self.assertGreater(start + width, cut)
        self.assertEqual(sum(scope == "long-stress" for *_, scope in recipes()), 6)


if __name__ == "__main__":
    unittest.main()
