#!/usr/bin/env python3
"""Collision witnesses, causal transform pairs and near-4GiB ring simulation."""
import hashlib
import random
import unittest

from search_extended_corpus import collision_keys, payload


def ring_transcript(window, offset):
    # Simulate the example's absolute-position links with a tiny shared bucket.
    # This is an arithmetic model, not a 4GiB native encode or a Rust proof.
    previous = [None] * window
    head, transcript = None, []
    for relative in range(window * 3 + 17):
        pos, found, candidates = relative + offset, head, []
        while found is not None and found < pos and pos - found <= window and len(candidates) < 64:
            candidates.append(pos - found)
            next_pos = previous[found & (window - 1)]
            if next_pos is not None and next_pos >= found:
                break
            found = next_pos
        transcript.append(candidates)
        previous[pos & (window - 1)], head = head, pos
    return transcript


class ExtensionTests(unittest.TestCase):
    def test_all_candidate_hashes_and_widths_have_exact_aligned_collision_witnesses(self):
        for kind in ('trigram', 'fourbyte', 'cost_trigram'):
            for bits in range(12, 19):
                keys, evidence = collision_keys(kind, bits, 32, random.Random(bits))
                self.assertEqual(len(set(keys)), 32)
                self.assertEqual(hashlib.sha256(b''.join(keys)).hexdigest(), evidence['keys_sha256'])

    def test_paired_transform_construction_preserves_recorded_base(self):
        for parameter in range(7):
            variants, evidence = payload('paired_transforms', parameter, 195115 + parameter, n=131072)
            self.assertEqual(len(variants), 2)
            self.assertEqual(hashlib.sha256(variants[0]).hexdigest(), evidence['base_sha256'])
            self.assertNotEqual(variants[0], variants[1])
            if evidence['transform'] == 'duplicate':
                self.assertEqual(variants[1], variants[0] * 2)

    def test_absolute_ring_distances_survive_4gib_boundary_without_large_allocation(self):
        for window in (16, 64, 256):
            offset = (1 << 32) - 2 * window
            self.assertEqual(ring_transcript(window, 0), ring_transcript(window, offset))
            self.assertTrue(all(0 < d <= window for row in ring_transcript(window, offset) for d in row))


if __name__ == '__main__':
    unittest.main()
