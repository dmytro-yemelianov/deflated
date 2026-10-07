#!/usr/bin/env python3
"""Export verified Bayesian-search rounds and censored wall-time evidence."""
import argparse
import gzip
import json
import pathlib
import statistics

from search_corpus import ROOT
from search_cpu import aggregate
from search_poc import sha


def publish(directory):
    report = json.loads((directory / 'result.json').read_text())
    for name, digest in report['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('measured Bayesian sources changed')
    if sha(directory / 'finalists.json') != report['finalists_sha256']:
        raise ValueError('training finalists changed')
    if json.loads((directory / 'finalists.json').read_text()) != report['finalists']:
        raise ValueError('finalist report differs from frozen selection')
    cases = {c['path'].split('/')[-1]: c for c in report['corpus']['cases'] if c['partition'] == 'train'}
    output = ROOT / 'scripts/reports'
    ledger = output / 'search-bayesian-measurements.jsonl.gz'
    count = 0
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as zipped:
        for index, study in enumerate(report['studies']):
            if sha(ROOT / study['binary_path']) != study['binary_sha256']:
                raise ValueError('native binary changed')
            for trial in study['training']:
                path = ROOT / study['directory'] / 'train' / trial['id']
                measured = json.loads((path / 'result.json').read_text())
                rows = measured['rows']
                if len(rows) != len(cases) or {r['input'] for r in rows} != set(cases):
                    raise ValueError('incomplete Bayesian raw matrix')
                if aggregate(rows) != trial['aggregate']:
                    raise ValueError('Bayesian aggregate differs from raw rounds')
                for row in rows:
                    for suffix, digest, size in (('.deflate', 'packed_sha256', 'packed_bytes'),
                                                  ('.baseline.deflate', 'baseline_packed_sha256', 'baseline_bytes')):
                        packed = path / 'streams' / (row['input'] + suffix)
                        if sha(packed) != row[digest] or packed.stat().st_size != row[size]:
                            raise ValueError('validated stream witness changed')
                    zipped.write((json.dumps({**row, 'study': index, 'trial_id': trial['id']}, separators=(',', ':'), allow_nan=False) + '\n').encode())
                    count += 1
    summaries = {}
    for strategy in report['protocol']['strategies']:
        studies = [s for s in report['studies'] if s['strategy'] == strategy]
        summaries[strategy] = {}
        for field, values in (
                ('unique_budget_hypervolume', [s['curve'][-1]['hypervolume'] for s in studies]),
                ('common_wall_hypervolume', [s['common_horizon']['hypervolume'] for s in studies]),
                ('common_wall_evaluations', [s['common_horizon']['unique_evaluations'] for s in studies]),
                ('search_seconds', [s['search_seconds'] for s in studies]),
                ('optimizer_fraction', [s['optimizer_fraction'] for s in studies]),
                ('instantaneous_optimizer_speedup_bound', [s['instantaneous_optimizer_speedup_bound'] for s in studies])):
            summaries[strategy][field] = {'median': statistics.median(values), 'minimum': min(values), 'maximum': max(values), 'values': values}
    report.update(summaries=summaries, raw_rows=count, raw_ledger=str(ledger.relative_to(ROOT)),
                  raw_ledger_sha256=sha(ledger), analysis_source_sha256=sha(pathlib.Path(__file__)))
    (output / 'search-bayesian.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/bayesian-search-report.md').write_text(render(report))
    print(json.dumps({'rows': count, 'ledger_bytes': ledger.stat().st_size}))


def render(report):
    p = report['protocol']
    lines = ['# S3: verified mixed-variable Bayesian search and wall-time frontiers', '',
             'This campaign compares fresh random, NSGA-II and multivariate MOTPE runs',
             'on the same native binary and 33 mixed training cases. Each strategy has',
             '32 unique configured evaluations across the same three seeds. Strategy',
             'order rotates; native measurements are serial, with other heavy local',
             'work paused. Each case uses five paired rounds with 5 ms minimum batches.',
             'Both candidate and Balanced streams pass three decoders. Reserved final',
             'tests and validation data are never encoded by this campaign.', '',
             '[Optuna 4.5 MOTPE](https://optuna.readthedocs.io/en/v4.5.0/reference/samplers/generated/optuna.samplers.TPESampler.html)',
             'uses 12 startup trials and 64 acquisition candidates, with multivariate',
             'group decomposition. Probe counts are log2 integers; lazy/index/token splits',
             'are categorical. Full insertion masks an inactive log2 tail field. This',
             'maps bijectively to the same 880 configurations as categorical NSGA-II',
             'and random search. Repeated proposals reuse verified feedback without',
             'charging another unique evaluation; cache hits remain recorded.', '',
             '## Evaluation budget and observed wall-time comparison', '',
             'Hypervolume minimizes normalized paired encoder time and exact size with',
             'a fixed (4, 1.5) reference and (1, 1) anchor. Presets/Stored are excluded',
             'from the optimizer frontiers. Wall time begins after the common four',
             'control encodes and includes optimizer setup, ask/cache/feedback, native',
             'encoding, three-decoder checks, source/corpus guards and ledger I/O.',
             'Compilation and controls are separately retained in the report.', '',
             f"The common observed horizon is {report['common_horizon_seconds']:.2f} seconds,",
             'the shortest completed configured-search clock. A result contributes only',
             'after its complete verification. Fixed checkpoints use only times observed',
             'in every run; stopped runs are never extrapolated.', '',
             '| Strategy | 32-evaluation HV median [range] | Common-time HV median [range] | Common-time evaluations median [range] |',
             '| --- | ---: | ---: | ---: |']
    for strategy, summary in report['summaries'].items():
        def cell(key, digits):
            v = summary[key]
            return f"{v['median']:.{digits}f} [{v['minimum']:.{digits}f}, {v['maximum']:.{digits}f}]"
        lines.append(f"| {strategy} | {cell('unique_budget_hypervolume',4)} | {cell('common_wall_hypervolume',4)} | {cell('common_wall_evaluations',0)} |")
    lines += ['', '## Time to predeclared hypervolume targets', '',
              '| Strategy / seed | HV 1.75, seconds | HV 1.8, seconds | Search duration, seconds |',
              '| --- | ---: | ---: | ---: |']
    for s in report['studies']:
        def reached(target):
            value = s['time_to_targets'][str(target)]
            return 'not reached (censored)' if value is None else f'{value:.2f}'
        lines.append(f"| {s['strategy']} / {s['seed']} | {reached(1.75)} | {reached(1.8)} | {s['search_seconds']:.2f} |")
    lines += ['', 'Three seeds support a bounded comparison; retain the ranges and avoid',
              'claiming statistical superiority. The configurations selected here still',
              'need frozen S9 validation before any production promotion.', '',
              'In this pilot MOTPE has the highest median frontier at both matched',
              'budgets and reaches HV 1.8 in all three seeds (47.7–69.8 seconds).',
              'Random and NSGA-II reach that target in two seeds each, with the other',
              'runs censored. Use CPU MOTPE as an additional research baseline; this',
              'supports better proposal selection here, not encoder superiority on fresh',
              'data. Keep all three strategies available for subsequent method spaces.', '',
              '## Whole-loop GPU decision', '',
              'S6 found worse latent prediction/ranking than explicit trees, overly wide',
              'calibration and a failed fitting-parity guard. Strict scoring passed but',
              'CPU was faster at 880 candidates. Here the actual CPU proposer fraction',
              'bounds the upside even if its entire setup/ask/feedback vanished.', '',
              '| Strategy | Optimizer fraction, median [range] | Instantaneous replacement bound, maximum |',
              '| --- | ---: | ---: |']
    for strategy, summary in report['summaries'].items():
        f, b = summary['optimizer_fraction'], summary['instantaneous_optimizer_speedup_bound']
        lines.append(f"| {strategy} | {100*f['median']:.3f}% [{100*f['minimum']:.3f}, {100*f['maximum']:.3f}] | {b['maximum']:.4f}× |")
    lines += ['', 'This is a measured whole-loop accounting bound, not a hypothetical',
              'trained-GPU speedup. GPU model fitting/conversion would add cost. Keep',
              'CPU proposal fallback for this workload; no GPU encoder is implemented.', '',
              '[Full evidence](../scripts/reports/search-bayesian.json) preserves canonical',
              'configs, raw optimizer records, per-trial completion clocks, frontiers,',
              'censoring, frozen training finalists and source/binary provenance.',
              f"The [paired gzip ledger](../scripts/reports/search-bayesian-measurements.jsonl.gz) contains {report['raw_rows']} rows.",
              'Git parent predates then-uncommitted search-tool changes; source hashes',
              'identify the measured revision. Production core/Lean sources are unchanged.', '',
              '```sh', 'target/search/optimizer-venv/bin/python scripts/search_bayesian_campaign.py --out target/search/bayesian/RUN',
              'python3 scripts/search_bayesian_report.py --campaign target/search/bayesian/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    publish(parser.parse_args().campaign.resolve())
