#!/usr/bin/env python3
"""Publish trained-model evidence without treating predictions as encodes."""
import argparse
import collections
import json
import pathlib
import shutil
import statistics
import zipfile

from search_corpus import ROOT
from search_poc import sha


def publish(directory):
    report = json.loads((directory / 'result.json').read_text())
    for name, digest in report['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('measured surrogate sources changed')
    ledger = directory / 'predictions.jsonl.gz'
    if sha(ledger) != report['prediction_ledger_sha256'] or sha(directory / 'dataset.json') != report['dataset_sha256']:
        raise ValueError('surrogate evidence changed')
    summaries = {}
    for kind in ('trees', 'explicit', 'latent'):
        entries = [r for r in report['fold_results'] if r['model'] == kind]
        groups = [g for entry in entries for g in entry['metrics']['groups']]
        ranks = [r for entry in entries for r in entry['metrics']['ranking']]
        summaries[kind] = {
            'group_balanced_mae_log': [statistics.mean(g['mae_log'][axis] for g in groups) for axis in (0, 1)],
            'whole_group_coverage': statistics.mean(g['all_rows_covered'] for g in groups),
            'mean_joint_row_coverage_by_group': statistics.mean(g['joint_row_coverage'] for g in groups),
            'mean_spearman': [statistics.mean(r['axes'][axis]['spearman'] for r in ranks if r['axes'][axis]['spearman'] is not None) for axis in (0, 1)],
            'mean_top32_overlap': [statistics.mean(r['axes'][axis]['top32_overlap'] for r in ranks) for axis in (0, 1)],
            'median_top1_relative_regret': [statistics.median(r['axes'][axis]['top1_relative_regret'] for r in ranks) for axis in (0, 1)],
            'fit_seconds': [e['fit_seconds'] for e in entries]}
        summaries[kind]['mean_fold_interval_half_width_log'] = [statistics.mean(e['metrics']['mean_interval_half_width_log'][axis] for e in entries) for axis in (0, 1)]
    output = ROOT / 'scripts/reports'
    target = output / 'search-surrogate-predictions.jsonl.gz'
    shutil.copyfile(ledger, target)
    archive = output / 'search-surrogate-models.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, digest in report['model_sha256'].items():
            path = directory / name
            if sha(path) != digest:
                raise ValueError('trained checkpoint changed')
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, path.read_bytes())
    report.update(summaries=summaries, prediction_ledger=str(target.relative_to(ROOT)),
                  model_archive=str(archive.relative_to(ROOT)), model_archive_sha256=sha(archive),
                  analysis_source_sha256=sha(pathlib.Path(__file__)))
    (output / 'search-surrogate.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/trained-surrogate-report.md').write_text(render(report))
    print(json.dumps({'rows': report['prediction_rows'], 'prediction_bytes': target.stat().st_size, 'model_bytes': archive.stat().st_size}))


def render(report):
    p = report['protocol']
    lines = ['# S6: trained explicit and latent encoder surrogates', '',
             f"The training ledger contains {report['provenance']['unique_labels']} unique file/config labels:",
             '33 training cases, 323 observed configurations, 21 source/family groups.',
             'Repeated measurements are collapsed to median log paired time ratios;',
             'exact packed sizes and hashes must agree. Features use only the training',
             'cases from S5. Neither prior validation targets nor reserved tests feed',
             'training, normalization or calibration.', '',
             'Three outer partitions each hold out seven complete source/family groups.',
             'Five additional groups calibrate uncertainty; the remaining nine fit models.',
             'A deterministic 65-config holdout is absent from both fitting and calibration.',
             'Held groups are scored on every observed configuration, including those',
             'unseen combinations. This is a joint extrapolation diagnostic. Parameters',
             'were frozen before fitting; there is no held-target hyperparameter sweep.', '',
             'Inputs contain 13 scaled integer workload features and categorical method',
             'and parameter indicators. Presets mask inactive configured axes. The',
             'baseline is 64 [Extra Trees](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html)',
             'with at least three rows per leaf. Explicit neural ensembles directly mix',
             'features and config indicators. Latent ensembles first learn a 16-dimensional',
             'workload bottleneck, then mix it with configuration indicators in a 128-wide',
             'hidden layer. Four members use group bootstrap and 800 minibatch Adam updates.',
             'The learned representation encodes sampled features, not raw input bytes.', '',
             '## Held prediction and ranking', '',
             '| Model | Group mean absolute log error, time / size | Mean Spearman, time / size | Top-32 overlap, time / size | Whole-group interval coverage | Mean fold half-width, log time / size |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for kind, summary in report['summaries'].items():
        def pair(key):
            return ' / '.join(f'{v:.3f}' for v in summary[key])
        lines.append(f"| {kind} | {pair('group_balanced_mae_log')} | {pair('mean_spearman')} | {pair('mean_top32_overlap')} | {summary['whole_group_coverage']:.1%} | {pair('mean_fold_interval_half_width_log')} |")
    lines += ['', 'Errors are in log ratios, so they are not percentage-point errors.',
              'Ranking averages weight each case equally; size ties are ranked with',
              'average ranks for correlation and stable config-ID order for top-32 overlap.',
              'All raw member predictions, targets and interval widths are retained.', '',
              'Uncertainty is ensemble spread with a 0.02 log-unit floor. Calibration',
              'uses the maximum joint standardized residual in each of five calibration',
              'groups and the finite-sample corrected 80% quantile. This can produce',
              'wide intervals. Coverage and width must be read together; neither small',
              'corpus exchangeability nor unseen-configuration coverage is guaranteed.', '',
              'Here the calibrated intervals are too wide for useful acquisition: even',
              'the tree model has mean time half-widths above five log units. High row',
              'coverage is therefore not evidence of a precise uncertainty estimate.', '',
              '## Trained CPU / Metal measurements', '',
              'The same trained first-fold latent network is scored with strict float32',
              '([MLX precision](https://ml-explore.github.io/mlx/build/html/usage/precision.html),',
              '[gradient transform](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.value_and_grad.html)).',
              'Inputs and weights are materialized, each device warmed twice, order rotated,',
              'and evaluation/synchronization completed before stopping the clock.',
              'The diagnostic ranking uses mean minus 0.1 spread; it is not an acquisition',
              'or a claimed compression result. Timing includes host result transfer.', '',
              '| Batch | CPU median, ms | GPU median, ms | GPU speed | Numeric check | Top-32 overlap |',
              '| --- | ---: | ---: | ---: | --- | ---: |']
    for row in report['scoring']:
        cpu, gpu = (statistics.median(row['samples_ns'][k]) / 1e6 for k in ('cpu', 'gpu'))
        lines.append(f"| {row['batch']} | {cpu:.3f} | {gpu:.3f} | {row['gpu_speedup']:.2f}× | {'pass' if row['precision_pass'] else 'fail'} | {row['top32_overlap']:.1%} |")
    fitting = report['fitting']
    cpu, gpu = (statistics.median(fitting['samples_seconds'][k]) for k in ('cpu', 'gpu'))
    lines += ['', f"Repeated fitting: CPU {cpu:.2f} s, GPU {gpu:.2f} s, GPU {fitting['gpu_speedup']:.2f}×.",
              'Three rotated repeats use identical initialization/bootstrap/minibatches.',
              'The clock charges initialization, conversion, bootstrap and 800 updates.',
              f"CPU/GPU fitted prediction scaled error: {fitting['max_scaled_prediction_error']:.3g}; "
              f"predeclared 0.005 check {'passes' if fitting['precision_pass'] else 'fails'}.", '',
              '## Decision scope', '',
              'The latent bottleneck improves absolute prediction error over the explicit',
              'neural model, but the trees are better on both objective errors and ranking.',
              'It fails the declared prediction/ranking/calibration case for replacing',
              'the explicit baseline. No encoder-evaluation saving has been demonstrated.',
              'The repeated CPU/GPU fitting discrepancy fails its predeclared numeric',
              'guard; retain that failed result and reject fitting parity. Scoring the',
              'same trained parameters passes. At 880 candidates CPU scoring is faster;',
              'the 65536-row GPU crossover does not justify GPU use in this search space.',
              'Device speed alone does not establish better proposals, fewer encoder',
              'evaluations, or a whole-search speedup. These observations evaluate already',
              'verified configurations; actual proposals still require native encoder and',
              'three-decoder checks. Keep CPU proposal machinery and production presets',
              'until a matched-budget whole-loop experiment supplies that evidence.', '',
              '[Full report](../scripts/reports/search-surrogate.json),',
              '[raw predictions](../scripts/reports/search-surrogate-predictions.jsonl.gz),',
              'and [trained neural checkpoints](../scripts/reports/search-surrogate-models.zip)',
              'retain partitions, calibration scores, model hashes, device/library versions',
              'and raw fitting/scoring rounds. Source hashes identify the then-uncommitted',
              'research scripts. The original encoder evidence remains authoritative for',
              'measured time/bytes; model outputs never replace it.', '',
              '```sh', 'python3 -m venv target/search/surrogate-venv',
              'target/search/surrogate-venv/bin/python -m pip install -r scripts/surrogate-requirements.txt',
              'target/search/surrogate-venv/bin/python scripts/search_surrogate.py --out target/search/surrogate/RUN',
              'python3 scripts/search_surrogate_report.py --campaign target/search/surrogate/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    publish(parser.parse_args().campaign.resolve())
