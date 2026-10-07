#!/usr/bin/env python3
"""Parser campaign boundaries and method roster, without native timing."""
from pathlib import Path
import unittest

from encoder_parse_campaign import cases, methods


class ParserPilotBoundary(unittest.TestCase):
    def test_new_test_rejected_before_reading_corpora(self):
        with self.assertRaisesRegex(ValueError, "inaccessible"):
            cases(Path("/missing-real"), Path("/missing-synthetic"), "test")

    def test_frozen_roster_has_distinct_bounded_methods(self):
        roster=methods()
        self.assertEqual(len(roster),24)
        self.assertEqual(len(set(roster)),24)
        self.assertEqual({name.split(":")[1] for name in roster},{"4","8","16"})
        self.assertEqual({name.split(":")[2] for name in roster},{"0","1"})
        self.assertEqual({name.split(":")[3] for name in roster if name.endswith(":1")},{"feedback"})


if __name__=="__main__":
    unittest.main()
