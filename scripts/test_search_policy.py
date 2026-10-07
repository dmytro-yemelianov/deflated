#!/usr/bin/env python3
"""Grouped selection leakage, guardrails and serialized native policy gates."""
import argparse
import copy
import json
import pathlib
import random
import subprocess
import tempfile
import unittest

from search_policy import features, fit, folds, nested, serialize, summary

BINARY = None


def fixtures():
    return [{'id': str(i), 'group': f'g{i}', 'features': [i] * 13, 'raw_bytes': 65536,
             'baseline_bytes': 100, 'baseline_ns': 100,
             'measurements': [{'packed_bytes': 100, 'encode_ns': 100},
                              {'packed_bytes': 100, 'encode_ns': 20 if i < 5 else 150}]}
            for i in range(10)]


class PolicyTests(unittest.TestCase):
    def test_grouped_folds_never_split_a_source_and_cover_every_case(self):
        cases = fixtures()
        cases.append({**cases[0], 'id': 'second-slice'})
        held = folds(cases, 5, 1)
        self.assertEqual({c['id'] for group in held for c in group}, {c['id'] for c in cases})
        for i, group in enumerate(held):
            own = {c['group'] for c in group}
            others = {c['group'] for j, g in enumerate(held) if i != j for c in g}
            self.assertFalse(own & others)

    def test_outer_targets_cannot_change_that_folds_inner_selection_or_tree(self):
        cases = fixtures()
        protocol = {'outer_folds': 5, 'inner_folds': 3, 'cv_seed': 19,
                    'depths': [-1, 0, 1, 2], 'minimum_leaf_cases': 2}
        initial = nested(cases, 'balanced', .01, protocol)
        poison = copy.deepcopy(cases)
        held = set(initial['outer'][0]['held_case_ids'])
        for case in poison:
            if case['id'] in held:
                case['measurements'][1].update(packed_bytes=10000, encode_ns=1)
        changed = nested(poison, 'balanced', .01, protocol)
        self.assertEqual(initial['outer'][0]['tree'], changed['outer'][0]['tree'])
        self.assertEqual(initial['outer'][0]['depth'], changed['outer'][0]['depth'])
        self.assertNotEqual(initial['outer'][0]['held_result'], changed['outer'][0]['held_result'])

    def test_a_fast_sampling_trap_fails_the_declared_size_guard(self):
        cases = fixtures()[:2]
        cases[1]['measurements'][1]['packed_bytes'] = 250
        result = summary(cases, [1, 1], 'speed', .2)
        self.assertFalse(result['feasible'])
        self.assertEqual(result['maximum_file_size_vs_balanced'], 2.5)
        node = fit(cases, 'speed', .2, 0)
        self.assertEqual(node, {'config': 0})

    def test_tiny_policy_fallback_does_not_relabel_static_control_costs(self):
        cases = fixtures()[:1]
        cases[0]['raw_bytes'] = 1
        self.assertEqual(summary(cases, [1], 'size', None)['encode_ns'], 100)
        self.assertEqual(summary(cases, [1], 'size', None, False)['encode_ns'], 20)

    def test_native_integer_features_match_python_across_boundaries_and_aliases(self):
        if not BINARY:
            self.skipTest('supply the native binary')
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'input.raw'
            for size in (0, 1, 2, 257, 258, 32767, 32768, 32769, 65536, 262144):
                for raw in (random.Random(size).randbytes(size), (bytes(range(64)) * ((size + 63) // 64))[:size]):
                    path.write_bytes(raw)
                    native = json.loads(subprocess.check_output([BINARY, '--features', str(path)], text=True))
                    self.assertEqual(native, features(raw))

    def test_native_loader_rejects_cycles_shared_unreachable_and_invalid_nodes(self):
        if not BINARY:
            self.skipTest('supply the native binary')
        header = 'policy-v1 features-13 short-balanced-32768\n'
        bad = ['B 0 1 0 1\nL balanced\n', 'B 0 1 1 1\nL balanced\n',
               'L balanced\nL fast\n', 'B 13 1 1 2\nL fast\nL best\n',
               'B 1 NaN 1 2\nL fast\nL best\n', 'L policy@recursive\n',
               'L balanced\n' * 512]
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'input.raw').write_bytes(b'x' * 65536)
            for text in bad:
                (root / 'model.policy').write_text(header + text)
                run = subprocess.run([BINARY, '--memory', str(root / 'input.raw'), str(root / 'out'),
                                      'policy@' + str(root / 'model.policy')], capture_output=True)
                self.assertNotEqual(run.returncode, 0)
            tree = {'feature': 1, 'threshold': 4.5, 'left': {'config': 0}, 'right': {'config': 1}}
            (root / 'model.policy').write_text(serialize(tree, ['balanced', 'fast']))
            subprocess.run([BINARY, '--memory', str(root / 'input.raw'), str(root / 'out'),
                            'policy@' + str(root / 'model.policy')], capture_output=True, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary')
    args = parser.parse_args()
    BINARY = args.binary
    unittest.main(argv=['test_search_policy.py'])
