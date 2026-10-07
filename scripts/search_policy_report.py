#!/usr/bin/env python3
"""Export S5 raw evidence and distinguish CV estimates from native timings."""
import argparse
import gzip
import json
import math
import pathlib
import statistics

from search_campaign import confidence
from search_corpus import ROOT
from search_cpu import aggregate
from search_poc import sha
from search_cpu import worker_method
from search_policy import choose, serialize


def export(directory):
    result = json.loads((directory / 'result.json').read_text())
    for name, digest in result['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('measured source revision changed before export')
    if sha(directory / 'frozen-policies.json') != result['frozen_sha256']:
        raise ValueError('policy freeze changed')
    if json.loads((directory / 'frozen-policies.json').read_text()) != result['fitted']:
        raise ValueError('reported policy differs from frozen fit')
    if json.loads((directory / 'training-matrix.json').read_text()) != result['matrix']:
        raise ValueError('reported training matrix differs from measured labels')
    if sha(ROOT / result['binary_path']) != result['binary_sha256']:
        raise ValueError('measured binary changed')
    methods = [worker_method(c) for c in result['protocol']['vocabulary']]
    for role, digest in result['policy_sha256'].items():
        if sha(directory / (role + '.policy')) != digest:
            raise ValueError('serialized policy changed')
        if (directory / (role + '.policy')).read_text() != serialize(result['fitted'][role]['tree'], methods):
            raise ValueError('serialized tree differs from fitted tree')
    output = ROOT / 'scripts/reports'
    ledger = output / 'search-policy-measurements.jsonl.gz'
    cases = result['corpus']['cases']
    counts = 0
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped:
        for event in result['events']:
            expected = {pathlib.PurePosixPath(c['path']).name: c for c in cases if c['partition'] == event['partition']}
            if len(event['rows']) != len(expected) or {r['input'] for r in event['rows']} != set(expected):
                raise ValueError('incomplete exported matrix')
            if aggregate(event['rows']) != event['aggregate']:
                raise ValueError('aggregate does not match raw rounds')
            for row in event['rows']:
                if row['raw_bytes'] != expected[row['input']]['bytes']:
                    raise ValueError('raw size differs from manifest')
                rounds = result['protocol']['training_rounds' if event['partition'] == 'train' else 'validation_rounds']
                for field in ('samples_ns', 'baseline_samples_ns'):
                    if len(row[field]) != rounds or not all(math.isfinite(x) and x > 0 for x in row[field]):
                        raise ValueError('missing or invalid paired rounds')
                for suffix, field, size in (('.deflate', 'packed_sha256', 'packed_bytes'),
                                            ('.baseline.deflate', 'baseline_packed_sha256', 'baseline_bytes')):
                    path = directory / event['label'] / 'streams' / (row['input'] + suffix)
                    if sha(path) != row[field] or path.stat().st_size != row[size]:
                        raise ValueError('packed witness changed')
                zipped.write((json.dumps({k: v for k, v in {**row, 'label': event['label'], 'partition': event['partition']}.items()},
                                         separators=(',', ':'), allow_nan=False) + '\n').encode())
                counts += 1
    expected_count = (len(methods) * sum(c['partition'] == 'train' for c in cases)
                      + (len(result['fitted']) + 3) * sum(c['partition'] == 'validation' for c in cases))
    if counts != expected_count or counts != result['verified_rows']:
        raise ValueError('incomplete campaign')
    scopes = {'real-regression': lambda c: c['family'] == 'real' and c['dataset'] == 'previous-regression',
              'real-fresh': lambda c: c['family'] == 'real' and c['dataset'] == 'fresh-calgary',
              'synthetic-regression': lambda c: c['family'] != 'real' and c['dataset'] == 'previous-regression',
              'synthetic-fresh': lambda c: c['dataset'] == 'fresh-synthetic'}
    control_summaries = []
    for measured in result['controls']:
        compact = {k: v for k, v in measured.items() if k != 'rows'}
        for scope, predicate in scopes.items():
            selected = [c for c in cases if c['partition'] == 'validation' and predicate(c)]
            names = {pathlib.PurePosixPath(c['path']).name for c in selected}
            rows = [r for r in measured['rows'] if r['input'] in names]
            compact[scope] = {'aggregate': aggregate(rows), 'confidence': confidence(rows, selected, 2000, result['protocol']['cv_seed'] + 2),
                              'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in rows)}
        control_summaries.append(compact)
    decisions = {}
    best = next(c for c in control_summaries if c['method'] == 'best')
    for measured in result['validation']:
        role = measured['role']
        tolerance = result['protocol']['roles'][role]
        decisions[role] = {}
        for scope in scopes:
            values, control = measured[scope], best[scope]
            size_ratio = values['aggregate']['size_vs_balanced']
            decisions[role][scope] = {
                'guard_pass': values['max_file_size_vs_balanced'] <= 1.2 and (role == 'size' or size_ratio <= 1 + tolerance),
                'packed_bytes_vs_best': values['aggregate']['packed_bytes'] / control['aggregate']['packed_bytes'],
                'selected_methods': sorted({methods[choose(result['fitted'][role]['tree'],
                                                          {'raw_bytes': c['bytes'], 'features': c['policy_features']})]
                                            for c in cases if c['partition'] == 'validation' and scopes[scope](c)})}
    report = {k: v for k, v in result.items() if k not in ('events', 'validation', 'controls')}
    report.update(validation=[{k: v for k, v in item.items() if k != 'rows'} for item in result['validation']],
                  controls=control_summaries, raw_rows=counts, raw_ledger=str(ledger.relative_to(ROOT)),
                  raw_ledger_sha256=sha(ledger), analysis_source_sha256=sha(pathlib.Path(__file__)),
                  decisions=decisions,
                  native_policies={role: (directory / (role + '.policy')).read_text() for role in result['fitted']},
                  training_events=[{k: v for k, v in event.items() if k != 'rows'} for event in result['events'] if event['partition'] == 'train'],
                  limitations=['CV uses encoder labels and excludes selector overhead; native validation charges all feature/selection cost',
                               'vocabulary was selected using prior training; CV is conditional on this vocabulary',
                               'old real/synthetic validation is regression evidence; fresh Calgary/synthetic scopes are separate',
                               'sampling and a finite source set cannot guarantee workload-general size constraints',
                               '26 final cases remain unencoded; no preset promotion, full S9 sessions or new-policy RSS yet'])
    path = output / 'search-policy.json'
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/context-policy-report.md').write_text(render(report))
    print(json.dumps({'report': str(path), 'raw_rows': counts, 'ledger_bytes': ledger.stat().st_size}))
    return report


def render(report):
    lines = ['# S5: workload-conditioned policies with charged native selection', '',
             'This experiment measures a frozen 11-method vocabulary on 39 training cases,',
             'fits bounded integer-feature trees using nested grouped validation, freezes',
             'the policies, then measures them on 39 validation cases. The original 14',
             'synthetic tests, six new synthetic tests and six Calgary files remain reserved.', '',
             'Vocabulary selection used the prior S2/S3 training evidence. Nested CV is',
             'conditional on that vocabulary. Previously visible full real files are',
             'regression evidence; seven Calgary files and six generated cases are separate',
             'fresh validation. Calgary pic was excluded because it duplicates an earlier',
             'source. Source/archive/payload hashes and an approximate sampled-shingle',
             'near-copy check are retained. [Corpus source](https://corpus.canterbury.ac.nz/descriptions/).', '',
             '## Selection and feature cost', '',
             'Thirteen integer features use at most 4096 staggered samples: length class,',
             'symbol concentration, equality at six lags, printable bytes and zeros.',
             'Rust/Python/manifest vectors must match exactly. Below 32 KiB the policy',
             'returns Balanced before feature extraction. Constant policies also skip',
             'feature extraction. Nonconstant features and selection run inside each',
             'timed native encode, together with allocation and emission.', '',
             'Five outer source/family folds evaluate selection; three inner folds choose',
             'depth -1/0/1/2/3, with at least three cases in a leaf. Depth -1 is the',
             'Balanced control. Held outer targets do not choose that fold\'s tree or depth.',
             'Leaves minimize summed paired-B-normalized encoder time subject to per-case',
             'training size bounds (+20% speed, +1% compromise), or exact summed size',
             'for the size role. CV also rejects aggregate/per-file regressions. CV scores',
             'estimate encoder cost from labels; the native measurements below include',
             'the additional policy cost. Every policy output hash must match an independently',
             'encoded Python-selected leaf, as well as passing all three decoders.', '',
             '| Role | Final depth | Nested estimated speed | Nested size change | Nested guards |',
             '| --- | ---: | ---: | ---: | --- |']
    for role, fitted in report['fitted'].items():
        s = fitted['nested_result']
        lines.append(f"| {role} | {fitted['full_training_depth']} | {s['speed_vs_balanced']:.2f}× | {100*(s['size_vs_balanced']-1):+.2f}% | {'pass' if s['feasible'] else 'fail'} |")
    for scope, title in [('real-regression', 'Previously visible full real files'), ('real-fresh', 'Fresh Calgary validation'),
                         ('synthetic-regression', 'Previous synthetic validation'), ('synthetic-fresh', 'Fresh synthetic regimes')]:
        lines += ['', '## ' + title, '', '| Method | Speed vs paired Balanced [95% interval] | Size change |',
                  '| --- | ---: | ---: |']
        for measured in report['validation'] + report['controls']:
            values = measured[scope]
            agg, ci = values['aggregate'], values['confidence']['speed_multiple_95pct']
            label = ('policy-' + measured['role']) if 'role' in measured else measured['method']
            lines.append(f"| {label} | {agg['speed_vs_paired_balanced']:.2f}× [{ci[0]:.2f}, {ci[1]:.2f}] | {100*(agg['size_vs_balanced']-1):+.2f}% |")
    lines += ['', '## Evidence and decision scope', '',
              'The speed role chose a constant 16-probe lazy trigram method with full insertion;',
              'the compromise chose Balanced. These results do not support useful context',
              'adaptation for either role. All three policies pass their predeclared validation',
              'size guards in each scope; the fixed Fast control exceeds the +20% per-file',
              'limit on synthetic data. Validation does not refit or reselect policies.', '',
              'The size tree chooses the 1024-probe trigram method when the largest sampled',
              'symbol count is at most 273, and Best otherwise, with the small-input fallback.',
              'On real files it mostly chooses Best. Its output is slightly larger than Best',
              'in both real scopes; the speed intervals overlap, and these are separate',
              'paired-B sessions rather than a direct tree-versus-Best timing experiment.',
              'Its previous synthetic scope is smaller than Best; fresh synthetic output',
              'is slightly larger. This is a bounded synthetic tradeoff, with no demonstrated',
              'general improvement over Best. Keep the production presets unchanged.', '',
              '| Scope | Size tree output change vs Best |',
              '| --- | ---: |']
    for scope in ('real-regression', 'real-fresh', 'synthetic-regression', 'synthetic-fresh'):
        lines.append(f"| {scope} | {100*(report['decisions']['size'][scope]['packed_bytes_vs_best']-1):+.4f}% |")
    lines += ['',
              '[Full evidence](../scripts/reports/search-policy.json) retains fold membership,',
              'all training labels, chosen depths, frozen trees, native policy text, source',
              'and binary provenance. The [raw gzip ledger](../scripts/reports/search-policy-measurements.jsonl.gz)',
              f"contains {report['raw_rows']} candidate/baseline measurement rows. Five training",
              'rounds use at least 5 ms batches; seven validation rounds use at least 10 ms.',
              'Confidence intervals resample source/family groups and paired rounds.', '',
              'The Git parent predates then-uncommitted research changes; the recorded source',
              'SHA map identifies the measured files. Core runtime dependencies and the Lean',
              'model are unchanged. Policy RSS, longer warm/cold sessions, decode/tiny-input',
              'and binary-size guardrails, latent prediction and final-test results remain',
              'subsequent investigation work, tracked by the completion audit.', '',
              '```sh', 'make research-policy-check', 'make research-policy',
              'python3 scripts/search_policy_report.py --campaign target/search/policies/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    args = parser.parse_args()
    export(args.campaign.resolve())
