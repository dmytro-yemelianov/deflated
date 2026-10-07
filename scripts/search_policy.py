#!/usr/bin/env python3
"""Bounded integer-feature policies; targets come only from verified encodes."""
import math
import random

FEATURE_NAMES = ['log2_length_floor', 'distinct', 'max_count', 'sum_squared_counts', 'samples',
                 'equal_lag_1', 'equal_lag_3', 'equal_lag_4', 'equal_lag_16', 'equal_lag_64',
                 'equal_lag_256', 'printable', 'zero']
SHORT_LIMIT = 32768


def features(raw):
    count, stride = min(len(raw), 4096), max(len(raw) // 4096, 1)
    histogram = [0] * 256
    values = [max(1, len(raw)).bit_length() - 1, 0, 0, 0, count] + [0] * 8
    for j in range(count):
        pos = j * stride + j * 0x9e3779b1 % stride
        byte = raw[pos]
        histogram[byte] += 1
        for k, distance in enumerate((1, 3, 4, 16, 64, 256)):
            values[5 + k] += pos >= distance and raw[pos - distance] == byte
        values[11] += 32 <= byte <= 126
        values[12] += byte == 0
    values[1:4] = [sum(c > 0 for c in histogram), max(histogram), sum(c * c for c in histogram)]
    return values


def chosen_measurement(case, config):
    return case['measurements'][0 if case['raw_bytes'] < SHORT_LIMIT else config]


def leaf(cases, role, tolerance):
    eligible = []
    for config in range(len(cases[0]['measurements'])):
        rows = [chosen_measurement(c, config) for c in cases]
        if role != 'size' and any(r['packed_bytes'] > c['baseline_bytes'] * (1 + tolerance)
                                  for r, c in zip(rows, cases)):
            continue
        size = sum(r['packed_bytes'] for r in rows)
        ns = sum(r['encode_ns'] for r in rows)
        eligible.append(((size, ns) if role == 'size' else (ns, size), config))
    if not eligible:
        raise ValueError('Balanced control must make every training leaf feasible')
    objective, config = min(eligible)
    return {'config': config}, objective[0]


def fit(cases, role, tolerance, depth, min_leaf=3):
    if not cases:
        raise ValueError('empty training fold')
    if depth == -1:
        return {'config': 0}
    node, loss = leaf(cases, role, tolerance)
    if depth == 0 or len(cases) < 2 * min_leaf:
        return node
    best = None
    for axis in range(len(FEATURE_NAMES)):
        values = sorted({c['features'][axis] for c in cases})
        for lower, upper in zip(values, values[1:]):
            threshold = (lower + upper) / 2
            left = [c for c in cases if c['features'][axis] <= threshold]
            right = [c for c in cases if c['features'][axis] > threshold]
            if min(len(left), len(right)) < min_leaf:
                continue
            cost = leaf(left, role, tolerance)[1] + leaf(right, role, tolerance)[1]
            key = cost, axis, threshold
            if cost < loss and (best is None or key < best[0]):
                best = key, left, right
    if best is None:
        return node
    (_, axis, threshold), left, right = best
    return {'feature': axis, 'threshold': threshold,
            'left': fit(left, role, tolerance, depth - 1, min_leaf),
            'right': fit(right, role, tolerance, depth - 1, min_leaf)}


def choose(tree, case):
    if case['raw_bytes'] < SHORT_LIMIT:
        return 0
    while 'config' not in tree:
        tree = tree['left' if case['features'][tree['feature']] <= tree['threshold'] else 'right']
    return tree['config']


def summary(cases, choices, role, tolerance, apply_short_fallback=True):
    rows = [chosen_measurement(c, k) if apply_short_fallback else c['measurements'][k]
            for c, k in zip(cases, choices)]
    ns = sum(r['encode_ns'] for r in rows)
    baseline_ns = sum(c['baseline_ns'] for c in cases)
    size = sum(r['packed_bytes'] for r in rows)
    baseline_size = sum(c['baseline_bytes'] for c in cases)
    maximum = max(r['packed_bytes'] / c['baseline_bytes'] for r, c in zip(rows, cases))
    ratio = size / baseline_size
    feasible = maximum <= 1.2 and (role == 'size' or ratio <= 1 + tolerance)
    return {'encode_ns': ns, 'packed_bytes': size, 'baseline_bytes': baseline_size,
            'speed_vs_balanced': baseline_ns / ns, 'size_vs_balanced': ratio,
            'maximum_file_size_vs_balanced': maximum, 'feasible': feasible,
            'objective': ratio if role == 'size' else ns / baseline_ns,
            'choices': choices}


def folds(cases, count, seed):
    groups = sorted({c['group'] for c in cases})
    if len(groups) < count:
        raise ValueError('insufficient independent groups')
    random.Random(seed).shuffle(groups)
    assignment = {g: i % count for i, g in enumerate(groups)}
    return [[c for c in cases if assignment[c['group']] == i] for i in range(count)]


def select_depth(cases, role, tolerance, protocol):
    held = folds(cases, protocol['inner_folds'], protocol['cv_seed'])
    evaluations = []
    for depth in protocol['depths']:
        ordered, choices = [], []
        for i, test in enumerate(held):
            training = [c for j, group in enumerate(held) if i != j for c in group]
            tree = fit(training, role, tolerance, depth, protocol['minimum_leaf_cases'])
            ordered.extend(test)
            choices.extend(choose(tree, c) for c in test)
        measured = summary(ordered, choices, role, tolerance)
        evaluations.append({'depth': depth, **measured})
    selected = min(evaluations, key=lambda e: (not e['feasible'], e['objective'], e['depth']))
    return selected['depth'], evaluations


def nested(cases, role, tolerance, protocol):
    held = folds(cases, protocol['outer_folds'], protocol['cv_seed'] + 1)
    ordered, predictions, evidence = [], [], []
    for i, test in enumerate(held):
        training = [c for j, group in enumerate(held) if i != j for c in group]
        depth, inner = select_depth(training, role, tolerance, protocol)
        tree = fit(training, role, tolerance, depth, protocol['minimum_leaf_cases'])
        choices = [choose(tree, c) for c in test]
        ordered.extend(test)
        predictions.extend(choices)
        evidence.append({'fold': i, 'training_groups': sorted({c['group'] for c in training}),
                         'held_groups': sorted({c['group'] for c in test}), 'depth': depth,
                         'inner': inner, 'tree': tree, 'held_case_ids': [c['id'] for c in test],
                         'held_result': summary(test, choices, role, tolerance)})
    depth, inner = select_depth(cases, role, tolerance, protocol)
    final = fit(cases, role, tolerance, depth, protocol['minimum_leaf_cases'])
    fixed = [summary(cases, [k] * len(cases), role, tolerance, False) for k in range(len(cases[0]['measurements']))]
    return {'nested_result': summary(ordered, predictions, role, tolerance), 'outer': evidence,
            'full_training_depth': depth, 'full_training_inner': inner, 'tree': final,
            'fixed_training_summaries': fixed,
            'limitation': 'vocabulary selected from earlier training evidence; nested CV assesses a policy conditional on that fixed vocabulary; fresh validation is separate'}


def serialize(tree, methods):
    nodes = []
    def visit(node):
        index = len(nodes)
        nodes.append(None)
        if 'config' in node:
            nodes[index] = 'L ' + methods[node['config']]
        else:
            left, right = visit(node['left']), visit(node['right'])
            nodes[index] = f"B {node['feature']} {node['threshold']!r} {left} {right}"
        return index
    visit(tree)
    return 'policy-v1 features-13 short-balanced-32768\n' + '\n'.join(nodes) + '\n'
