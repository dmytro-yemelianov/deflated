"""Training-only, deduplicated labels and leakage-safe surrogate partitions."""
import collections
import gzip
import json
import math
import random
import statistics

from search_cpu import AXES, canonical, identity
from search_poc import sha


def context_vector(values):
    n = max(1, values[4])
    return [values[0] / 32, values[1] / 256, values[2] / n, values[3] / n ** 2,
            values[4] / 4096] + [v / n for v in values[5:]]


def config_vector(config):
    canonical(config)
    if 'reference' in config:
        raise ValueError('reference encoders are outside the surrogate method vocabulary')
    # Methods are categorical; inactive axes are masked, never numeric guesses.
    method = [float(config.get('preset') == name) for name in ('balanced', 'fast', 'best', 'stored')]
    active = set(config) == set(AXES)
    return method + [float(active)] + [float(active and config[axis] == value)
                                      for axis, values in AXES.items() for value in values]


def load_training(root):
    path = root / 'scripts/reports/search-campaign.json'
    report = json.loads(path.read_text())
    ledger = root / report['raw_ledger']
    if sha(ledger) != report['raw_ledger_sha256']:
        raise ValueError('campaign ledger hash changed')
    policy_path = root / 'scripts/reports/search-policy.json'
    policy = json.loads(policy_path.read_text())
    contexts = {c['sha256']: c for c in policy['corpus']['cases'] if c['partition'] == 'train'}
    cases = {c['path'].split('/')[-1]: c for c in report['corpus']['cases'] if c['partition'] == 'train'}
    configs = {t['id']: t['config'] for s in report['studies'] for t in s['training']}
    repeated = collections.defaultdict(list)
    with gzip.open(ledger, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            if row['phase'] == 'train':
                if row['input'] not in cases or row['trial_id'] not in configs:
                    raise ValueError('unknown training label')
                repeated[row['input'], row['trial_id']].append(row)
    records = []
    for (name, key), rows in sorted(repeated.items()):
        case = cases[name]
        feature_case = contexts[case['sha256']]
        if len({(r['packed_bytes'], r['baseline_bytes'], r['packed_sha256'], r['baseline_packed_sha256']) for r in rows}) != 1:
            raise ValueError('duplicate configs disagree on exact byte witnesses')
        if identity(configs[key]) != key:
            raise ValueError('noncanonical config label')
        times = [math.log(statistics.median(r['samples_ns']) / statistics.median(r['baseline_samples_ns'])) for r in rows]
        records.append({'id': name + ':' + key, 'case': name, 'config_id': key,
                        'group': 'real:' + case['source_file'] if case['family'] == 'real' else 'synthetic:' + case['family'],
                        'context': context_vector(feature_case['policy_features']), 'config': configs[key],
                        'x': context_vector(feature_case['policy_features']) + config_vector(configs[key]),
                        'y': [statistics.median(times), math.log(rows[0]['packed_bytes'] / rows[0]['baseline_bytes'])],
                        'repeat_log_time_range': max(times) - min(times), 'repeats': len(rows)})
    if len(records) != len(cases) * len(configs):
        raise ValueError('training label matrix is incomplete')
    return records, {'campaign_report_sha256': sha(path), 'ledger_sha256': sha(ledger),
                     'feature_report_sha256': sha(policy_path), 'feature_source_sha256': policy['source_sha256']['scripts/search_policy.py'],
                     'case_count': len(cases), 'config_count': len(configs), 'groups': len({r['group'] for r in records}),
                     'raw_rows': sum(len(rows) for rows in repeated.values()), 'unique_labels': len(records),
                     'targets': ['log paired time / Balanced', 'log exact packed bytes / Balanced'],
                     'validation_or_test_labels_used': False}


def partitions(records, protocol):
    groups = sorted({r['group'] for r in records})
    random.Random(protocol['seed']).shuffle(groups)
    configs = sorted({r['config_id'] for r in records})
    random.Random(protocol['seed'] + 1).shuffle(configs)
    unseen = set(configs[::protocol['config_holdout_stride']])
    plans = []
    for fold in range(protocol['folds']):
        held = set(groups[fold::protocol['folds']])
        rest = [g for g in groups if g not in held]
        random.Random(protocol['seed'] + 100 + fold).shuffle(rest)
        calibration = set(rest[:protocol['calibration_groups']])
        fitted = set(rest[protocol['calibration_groups']:])
        if not fitted or fitted & held or fitted & calibration or held & calibration:
            raise ValueError('invalid grouped partition')
        plans.append({'fold': fold, 'fit_groups': sorted(fitted), 'calibration_groups': sorted(calibration),
                      'held_groups': sorted(held), 'unseen_configs': sorted(unseen),
                      'fit': [i for i, r in enumerate(records) if r['group'] in fitted and r['config_id'] not in unseen],
                      'calibration': [i for i, r in enumerate(records) if r['group'] in calibration and r['config_id'] not in unseen],
                      'held': [i for i, r in enumerate(records) if r['group'] in held]})
    return plans


def group_quantile(scores, coverage):
    ordered = sorted(scores)
    rank = math.ceil((len(ordered) + 1) * coverage)
    if not ordered or rank > len(ordered):
        raise ValueError('not enough calibration groups for a finite corrected quantile')
    return ordered[rank - 1]
