#!/usr/bin/env python3
"""Normative error precedence and independent arithmetic/member witnesses."""

import json
from pathlib import Path
import random
import unittest

from structured_reference import Cursor, DecodeError, decode, frame, normative_vectors, varint


class ReferenceTests(unittest.TestCase):
    def test_published_vectors_are_current_and_correct(self):
        published = Path(__file__).resolve().parents[1] / "tests/structured/vectors.json"
        data = json.loads(published.read_text())
        # Valid DEFLATE bytes need not be identical across zlib encoder versions.
        # Keep the committed packets authoritative and compare their semantic
        # expectations to the independently constructed vector definitions.
        expected = normative_vectors()
        self.assertEqual(data.keys(), expected.keys())
        self.assertEqual([{k: v for k, v in row.items() if k != "packet_hex"}
                          for row in data["vectors"]],
                         [{k: v for k, v in row.items() if k != "packet_hex"}
                          for row in expected["vectors"]])
        for vector in data["vectors"]:
            with self.subTest(vector=vector["name"]):
                packet = bytes.fromhex(vector["packet_hex"])
                if "error" in vector:
                    with self.assertRaises(DecodeError) as error:
                        decode(packet, vector["limit"])
                    self.assertEqual(error.exception.category, vector["error"])
                else:
                    self.assertEqual(decode(packet, vector["limit"]), bytes.fromhex(vector["raw_hex"]))

    def test_varints_at_all_group_boundaries(self):
        witnesses = {0, (1 << 64) - 1}
        for bits in range(1, 64):
            witnesses.update(((1 << bits) - 1, 1 << bits, (1 << bits) + 1))
        for value in witnesses:
            cursor = Cursor(varint(value))
            self.assertEqual(cursor.varint(), value)
            self.assertEqual(cursor.remaining(), 0)
        for malformed, category in [(b"\x80\0", "noncanonicalVarint"),
                                    (b"\x80" * 10, "integerOverflow"),
                                    (b"\xff" * 9 + b"\x7f", "integerOverflow")]:
            with self.assertRaises(DecodeError) as error:
                Cursor(malformed).varint()
            self.assertEqual(error.exception.category, category)

    def test_all_truncations_and_single_byte_mutations(self):
        # Exact expected output is authoritative even if a CRC collision or an
        # unused DEFLATE padding-bit mutation remains a valid frame.
        published = Path(__file__).resolve().parents[1] / "tests/structured/vectors.json"
        for vector in json.loads(published.read_text())["vectors"]:
            if "raw_hex" not in vector:
                continue
            packet = bytes.fromhex(vector["packet_hex"])
            expected = bytes.fromhex(vector["raw_hex"])
            for end in range(len(packet)):
                with self.assertRaises(DecodeError):
                    decode(packet[:end])
            for position in range(len(packet)):
                changed = bytearray(packet)
                changed[position] ^= 1
                try:
                    raw = decode(changed)
                except DecodeError:
                    continue
                self.assertEqual(raw, expected)

    def test_raw_byte_domain(self):
        rng = random.Random(13014)
        for length in (0, 1, 2, 255, 256, 65535, 65536):
            raw = rng.randbytes(length)
            self.assertEqual(decode(frame(raw)), raw)


if __name__ == "__main__":
    unittest.main()
