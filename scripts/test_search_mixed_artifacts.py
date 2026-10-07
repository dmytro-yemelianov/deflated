#!/usr/bin/env python3
"""Reconstruct matrix, matched-size monotonicity and actual packet cost witnesses."""
import collections
import gzip
import hashlib
import json
import math
import pathlib
import unittest

from search_cpu import aggregate
from search_poc import decode_exact
from test_search_mixed import exhaustive, stored_bits


class MixedArtifactTests(unittest.TestCase):
    def test_native_matrix_matched_controls_and_training_freeze(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / 'scripts/reports/search-mixed.json').read_text())
        payload = (root / report['raw_ledger']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report['raw_ledger_sha256'])
        rows = [json.loads(line) for line in gzip.decompress(payload).splitlines()]
        self.assertEqual(len(rows), report['raw_rows'])
        self.assertEqual(len(rows), report['verified_rows'])
        measured = collections.defaultdict(list)
        for row in rows:
            measured[row['partition'], row['config_id']].append(row)
        keys = set()
        for event in report['training'] + report['validation']:
            key = event['partition'], event['id']
            self.assertNotIn(key, keys)
            keys.add(key)
            observations = measured[key]
            cases = {pathlib.PurePosixPath(c['path']).name: c for c in report['corpus']['cases'] if c['partition'] == event['partition']}
            self.assertEqual(len(observations), len(cases))
            self.assertEqual({r['input'] for r in observations}, set(cases))
            self.assertEqual(hashlib.sha256(json.dumps(event['config'], sort_keys=True).encode()).hexdigest(), event['id'])
            self.assertEqual(aggregate(observations), event['aggregate'])
            for row in observations:
                self.assertEqual(row['raw_bytes'], cases[row['input']]['bytes'])
                for field in ('samples_ns', 'baseline_samples_ns'):
                    self.assertEqual(len(row[field]), report['protocol']['training_rounds' if key[0] == 'train' else 'validation_rounds'])
                    self.assertTrue(all(math.isfinite(v) and v > 0 for v in row[field]))
                for field in ('packed_sha256', 'baseline_packed_sha256'):
                    self.assertEqual(len(bytes.fromhex(row[field])), 32)
        self.assertEqual(keys, set(measured))
        for partition, events in (('train', report['training']), ('validation', report['validation'])):
            methods = {e['config']['method']: measured[partition, e['id']] for e in events}
            for level in report['protocol']['levels']:
                for limit in report['protocol']['token_limits']:
                    controls = {r['input']: r['packed_bytes'] for r in methods[f'compressed:{level}:{limit}']}
                    for row in methods[f'mixed:{level}:{limit}']:
                        self.assertLessEqual(row['packed_bytes'], controls[row['input']])
        eligible = [e for e in report['training'] if e['max_file_size_vs_balanced'] <= report['protocol']['guardrails']['maximum_file_size_vs_balanced']]
        self.assertEqual(report['finalists']['roles']['size'], min(eligible, key=lambda e: (e['aggregate']['packed_bytes'], e['aggregate']['time_vs_paired_balanced']))['id'])
        self.assertFalse(report['reserved_tests_encoded'])
        self.assertEqual(report['promotion'], 'none')

    def test_retained_packet_costs_match_exhaustive_type_oracle(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        report = json.loads((root / 'scripts/reports/search-mixed.json').read_text())
        for witness in report['witnesses']:
            raw = bytes.fromhex(witness['raw_hex'])
            packet = bytes.fromhex(witness['packed_hex'])
            decode_exact(packet, raw)
            self.assertEqual(len(packet), (witness['emitted_bits'] + 7) // 8)
            if witness['fallback']:
                self.assertEqual(len(packet), len(raw) + max(1, (len(raw) + 65534) // 65535) * 5)
                continue
            blocks = witness['blocks']
            costs = [(b['fixed_bits'], b['dynamic_bits'], b['raw_bytes']) for b in blocks]
            self.assertEqual(exhaustive(costs, 0, witness['method'].startswith('mixed:')), witness['planned_bits'])
            offset, total = 0, 0
            for block in blocks:
                self.assertEqual(offset, block['start_offset'])
                bits = block['fixed_bits'] if block['kind'] == 'Fixed' else block['dynamic_bits'] if block['kind'] == 'Dynamic' else stored_bits(block['raw_bytes'], offset)
                self.assertEqual(bits, block['emitted_bits'])
                offset = (offset + bits) % 8
                total += bits
            self.assertEqual(sum(b['raw_bytes'] for b in blocks), len(raw))
            self.assertEqual(total, witness['emitted_bits'])
            self.assertEqual(len(packet) * 8, witness['planned_bits'])


if __name__ == '__main__':
    unittest.main()
