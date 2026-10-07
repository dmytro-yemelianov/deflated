#!/usr/bin/env python3
"""Check leakage guards with shifted copies and declared lineage reuse."""
import copy
import gzip
import json
import random
import unittest
from unittest.mock import patch

from new_methods_corpus import INVENTORY, chunks, copied, extract, inventory_check


class AcquisitionGuards(unittest.TestCase):
    def test_shifted_and_mutated_copy(self):
        rng = random.Random(1487)
        raw = rng.randbytes(65536)
        shifted = b"arbitrary unaligned prefix" + raw + b"suffix"
        self.assertTrue(copied(raw, shifted, chunks(raw), chunks(shifted)))
        changed = bytearray(shifted)
        for offset in range(2000, len(changed), 16000):
            changed[offset:offset + 32] = rng.randbytes(32)
        self.assertTrue(copied(raw, bytes(changed), chunks(raw), chunks(changed)))
        other = rng.randbytes(len(raw))
        self.assertFalse(copied(raw, other, chunks(raw), chunks(other)))

    def test_pinned_source_and_old_lineage(self):
        inventory = json.loads(INVENTORY.read_text())
        inventory_check(inventory)
        changed = copy.deepcopy(inventory)
        changed["sources"][-1]["lineage"] = changed["sources"][0]["lineage"]
        with self.assertRaisesRegex(ValueError, "repeated lineage"):
            inventory_check(changed)
        changed = copy.deepcopy(inventory)
        changed["sources"][0]["lineage"] = "python/cpython"
        with self.assertRaisesRegex(ValueError, "previously measured"):
            inventory_check(changed)
        changed = copy.deepcopy(inventory)
        changed["sources"][0]["pinned_commit"] = "HEAD"
        with self.assertRaisesRegex(ValueError, "unversioned"):
            inventory_check(changed)

    def test_gzip_corruption_and_expansion_limit(self):
        source = {"extraction": "gzip"}
        packed = gzip.compress(b"a" * 513, mtime=0)
        with patch("new_methods_corpus.DOWNLOAD_LIMIT", 512):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                extract(source, packed)
        with self.assertRaises((EOFError, gzip.BadGzipFile)):
            extract(source, packed[:-3])


if __name__ == "__main__":
    unittest.main()
