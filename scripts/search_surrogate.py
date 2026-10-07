#!/usr/bin/env python3
"""Trained explicit/latent ensembles, grouped calibration and device timings.

This predicts verified encoder labels. It does not evaluate new configurations
or promote a compression method. MLX is an optional Apple-silicon dependency.
"""
import argparse
import gzip
import importlib.metadata
import json
import os
import pathlib
import platform
import statistics
import subprocess
import time

os.environ['MLX_ENABLE_TF32'] = '0'
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

from search_corpus import ROOT
from search_cpu import write_json
from search_poc import sha
from search_surrogate_data import group_quantile, load_training, partitions


def forward(mx, params, x, kind):
    members = params['w1'].shape[0]
    x = mx.broadcast_to(x, (members, *x.shape[-2:]))
    if kind == 'latent':
        latent = mx.maximum(x[:, :, :13] @ params['we'] + params['be'], 0)
        x = mx.concatenate([latent, x[:, :, 13:]], axis=-1)
    hidden = mx.maximum(x @ params['w1'] + params['b1'], 0)
    return hidden @ params['w2'] + params['b2']


def fit_neural(np, mx, x, y, groups, kind, device, protocol, seed):
    begun = time.perf_counter()
    rng = np.random.default_rng(seed)
    members, hidden = protocol['ensemble_members'], protocol['hidden_width']
    latent = protocol['latent_width']
    def weight(a, b):
        return mx.array(rng.normal(0, (2 / a) ** .5, (members, a, b)).astype(np.float32))
    with mx.stream(device):
        params = {'w1': weight(latent + x.shape[1] - 13 if kind == 'latent' else x.shape[1], hidden),
                  'b1': mx.zeros((members, 1, hidden)), 'w2': weight(hidden, 2), 'b2': mx.zeros((members, 1, 2))}
        if kind == 'latent':
            params.update(we=weight(13, latent), be=mx.zeros((members, 1, latent)))
        vx, vy = mx.array(x), mx.array(y)
        moment = {k: mx.zeros_like(v) for k, v in params.items()}
        variance = {k: mx.zeros_like(v) for k, v in params.items()}
        mx.eval(params, moment, variance, vx, vy)
        unique_groups = sorted(set(groups))
        by_group = {g: np.flatnonzero(np.array(groups) == g) for g in unique_groups}
        pools = []
        for _ in range(members):
            sampled = rng.choice(unique_groups, len(unique_groups), replace=True)
            pools.append(np.concatenate([by_group[g] for g in sampled]))
        def loss(p, bx, by):
            return mx.mean((forward(mx, p, bx, kind) - by) ** 2)
        gradient = mx.value_and_grad(loss)
        losses = []
        for step in range(1, protocol['training_steps'] + 1):
            indices = mx.array(np.stack([rng.choice(pool, protocol['batch_size']) for pool in pools]).astype(np.int32))
            value, grads = gradient(params, vx[indices], vy[indices])
            for key in params:
                grad = grads[key] + protocol['weight_decay'] * params[key]
                moment[key] = .9 * moment[key] + .1 * grad
                variance[key] = .999 * variance[key] + .001 * grad ** 2
                params[key] = params[key] - protocol['learning_rate'] * (moment[key] / (1 - .9 ** step)) / (mx.sqrt(variance[key] / (1 - .999 ** step)) + 1e-8)
            mx.eval(params, moment, variance, value)
            if step == 1 or step == protocol['training_steps'] or step % 100 == 0:
                losses.append({'step': step, 'mse_standardized': float(value.item())})
    mx.synchronize(device)
    return params, time.perf_counter() - begun, losses


def predict_neural(np, mx, params, x, kind, device, target_mean, target_scale):
    with mx.stream(device):
        values = forward(mx, params, mx.array(x), kind)
        mx.eval(values)
    mx.synchronize(device)
    return np.array(values) * target_scale + target_mean


def metrics(np, records, indices, prediction, radius):
    from scipy.stats import spearmanr
    targets = np.array([records[i]['y'] for i in indices])
    mean, spread = prediction.mean(axis=0), prediction.std(axis=0)
    error = np.abs(targets - mean)
    covered = np.all(error <= radius, axis=1)
    groups = sorted({records[i]['group'] for i in indices})
    grouped = []
    for group in groups:
        where = [j for j, i in enumerate(indices) if records[i]['group'] == group]
        grouped.append({'group': group, 'mae_log': error[where].mean(axis=0).tolist(),
                        'joint_row_coverage': float(covered[where].mean()), 'all_rows_covered': bool(covered[where].all())})
    ranking = []
    for case in sorted({records[i]['case'] for i in indices}):
        where = [j for j, i in enumerate(indices) if records[i]['case'] == case]
        axes = []
        for axis in (0, 1):
            truth, estimated = targets[where, axis], mean[where, axis]
            true_order, predicted_order = np.argsort(truth, kind='stable'), np.argsort(estimated, kind='stable')
            correlation = float(spearmanr(truth, estimated).statistic) if np.std(truth) > 0 and np.std(estimated) > 0 else None
            k = min(32, len(where))
            axes.append({'spearman': correlation, 'top32_overlap': len(set(true_order[:k]) & set(predicted_order[:k])) / k,
                         'top1_relative_regret': float(np.exp(truth[predicted_order[0]] - truth.min()) - 1)})
        ranking.append({'case': case, 'axes': axes})
    return {'rows': len(indices), 'groups': grouped,
            'group_balanced_mae_log': np.mean([g['mae_log'] for g in grouped], axis=0).tolist(),
            'joint_row_coverage': float(covered.mean()), 'whole_group_coverage': sum(g['all_rows_covered'] for g in grouped) / len(grouped),
            'mean_interval_half_width_log': np.mean(radius, axis=0).tolist(),
            'raw_ensemble_spread_log': spread.mean(axis=0).tolist(), 'ranking': ranking}


def calibrate(np, records, indices, prediction, protocol):
    truth = np.array([records[i]['y'] for i in indices])
    scores = np.max(np.abs(truth - prediction.mean(axis=0)) / np.maximum(protocol['uncertainty_floor_log'], prediction.std(axis=0)), axis=1)
    by_group = {}
    for j, index in enumerate(indices):
        group = records[index]['group']
        by_group[group] = max(by_group.get(group, 0), float(scores[j]))
    quantile = group_quantile(list(by_group.values()), protocol['coverage'])
    return quantile, {'group_max_scores': by_group, 'quantile': quantile, 'coverage_target': protocol['coverage'],
                      'scope': 'group-max finite-sample corrected quantile; conditional config extrapolation is diagnostic, no distribution-free claim'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_surrogate_protocol.json')
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import mlx.core as mx
    from sklearn.ensemble import ExtraTreesRegressor
    if not mx.metal.is_available():
        raise SystemExit('Metal unavailable; this optional experiment needs Apple silicon')
    for package, version in (('numpy', '2.5.3'), ('scikit-learn', '1.9.1'), ('mlx', '0.32.1')):
        if importlib.metadata.version(package) != version:
            raise ValueError('use pinned surrogate dependencies')
    args.out.mkdir(parents=True, exist_ok=False)
    begun = time.perf_counter()
    protocol = json.loads(args.protocol.read_text())
    sources = {name: sha(ROOT / name) for name in ('scripts/search_surrogate.py', 'scripts/search_surrogate_data.py', 'scripts/search_surrogate_protocol.json')}
    records, provenance = load_training(ROOT)
    plans = partitions(records, protocol)
    x, y = np.array([r['x'] for r in records], np.float32), np.array([r['y'] for r in records], np.float32)
    write_json(args.out / 'dataset.json', records)
    write_json(args.out / 'partitions.json', plans)
    evidence, observations = [], []
    device_material = None
    for plan in plans:
        fit, calibration, held = plan['fit'], plan['calibration'], plan['held']
        # Fit-only normalization. Neither calibration nor held targets set it.
        x_mean, x_scale = x[fit].mean(axis=0), np.maximum(x[fit].std(axis=0), 1e-5)
        y_mean, y_scale = y[fit].mean(axis=0), np.maximum(y[fit].std(axis=0), .01)
        nx, ny = np.clip((x - x_mean) / x_scale, -8, 8), (y - y_mean) / y_scale
        groups = [records[i]['group'] for i in fit]
        for kind in ('trees', 'explicit', 'latent'):
            print('fit', plan['fold'], kind, len(fit), flush=True)
            seed = protocol['seed'] + plan['fold']
            if kind == 'trees':
                started = time.perf_counter()
                forest = ExtraTreesRegressor(n_estimators=protocol['trees'], min_samples_leaf=protocol['tree_minimum_leaf'], n_jobs=1, random_state=seed)
                forest.fit(nx[fit], y[fit])
                elapsed, losses = time.perf_counter() - started, []
                predict = lambda subset: np.stack([tree.predict(nx[subset]) for tree in forest.estimators_])
                params = None
            else:
                params, elapsed, losses = fit_neural(np, mx, nx[fit], ny[fit], groups, kind, mx.gpu, protocol, seed)
                predict = lambda subset: predict_neural(np, mx, params, nx[subset], kind, mx.gpu, y_mean, y_scale)
                np.savez_compressed(args.out / f"fold-{plan['fold']}-{kind}.npz", **{k: np.array(v) for k, v in params.items()},
                                    x_mean=x_mean, x_scale=x_scale, y_mean=y_mean, y_scale=y_scale)
            calibration_prediction, held_prediction = predict(calibration), predict(held)
            quantile, calibration_evidence = calibrate(np, records, calibration, calibration_prediction, protocol)
            radius = quantile * np.maximum(protocol['uncertainty_floor_log'], held_prediction.std(axis=0))
            report = metrics(np, records, held, held_prediction, radius)
            for j, index in enumerate(held):
                observations.append({'fold': plan['fold'], 'model': kind, 'id': records[index]['id'], 'group': records[index]['group'],
                                     'case': records[index]['case'], 'config_id': records[index]['config_id'],
                                     'config_unseen': records[index]['config_id'] in plan['unseen_configs'],
                                     'target_log': records[index]['y'], 'predicted_members_log': held_prediction[:, j].tolist(),
                                     'interval_half_width_log': radius[j].tolist()})
            evidence.append({'fold': plan['fold'], 'model': kind, 'fit_seconds': elapsed, 'loss': losses,
                             'calibration': calibration_evidence, 'metrics': report})
            if plan['fold'] == 0 and kind == 'latent':
                device_material = params, nx, ny, fit, held, groups, y_mean, y_scale
    params, nx, ny, fit, held, groups, y_mean, y_scale = device_material
    scoring = []
    for batch in protocol['scoring_batches']:
        with mx.stream(mx.cpu):
            material = mx.array(nx[np.arange(batch) % len(nx)])
            mx.eval(material)
        def score(device):
            with mx.stream(device):
                prediction = forward(mx, params, material, 'latent')
                mean, spread = prediction.mean(axis=0), prediction.std(axis=0)
                # Diagnostic LCB ranking, not a Bayesian acquisition or encoder result.
                ranking = mx.argsort(mean.mean(axis=1) - .1 * spread.mean(axis=1))[:min(32, batch)]
                mx.eval(prediction, ranking)
            mx.synchronize(device)
            return np.array(prediction), ranking.tolist()
        results = {name: score(device) for name, device in (('cpu', mx.cpu), ('gpu', mx.gpu))}
        for device in (mx.cpu, mx.gpu):
            score(device)
        timings = {'cpu': [], 'gpu': []}
        for repeat in range(protocol['timing_rounds']):
            devices = [('cpu', mx.cpu), ('gpu', mx.gpu)]
            if repeat % 2:
                devices.reverse()
            for name, device in devices:
                started = time.perf_counter_ns()
                score(device)
                timings[name].append(time.perf_counter_ns() - started)
        cpu, gpu = results['cpu'], results['gpu']
        error = float(np.max(np.abs(cpu[0] - gpu[0]) / (1 + np.abs(cpu[0]))))
        overlap = len(set(cpu[1]) & set(gpu[1])) / len(cpu[1])
        scoring.append({'batch': batch, 'samples_ns': timings, 'gpu_speedup': statistics.median(timings['cpu']) / statistics.median(timings['gpu']),
                        'max_scaled_error': error, 'top32_overlap': overlap, 'precision_pass': error <= protocol['scoring_tolerance'],
                        'scope': 'materialized trained network plus diagnostic LCB rank and host result transfer; no encoder evaluation'})
        print('score', batch, scoring[-1]['gpu_speedup'], flush=True)
    print('fit-crossover', flush=True)
    fit_times, fitted_predictions = {'cpu': [], 'gpu': []}, {}
    warm = {**protocol, 'training_steps': 10}
    for device in (mx.cpu, mx.gpu):
        fit_neural(np, mx, nx[fit], ny[fit], groups, 'latent', device, warm, protocol['seed'])
    for repeat in range(protocol['fitting_repeats']):
        devices = [('cpu', mx.cpu), ('gpu', mx.gpu)]
        if repeat % 2:
            devices.reverse()
        for name, device in devices:
            fitted, elapsed, _ = fit_neural(np, mx, nx[fit], ny[fit], groups, 'latent', device, protocol, protocol['seed'])
            fit_times[name].append(elapsed)
            fitted_predictions[name] = predict_neural(np, mx, fitted, nx[held], 'latent', device, y_mean, y_scale)
    fit_error = float(np.max(np.abs(fitted_predictions['cpu'] - fitted_predictions['gpu']) / (1 + np.abs(fitted_predictions['cpu']))))
    fitting = {'samples_seconds': fit_times, 'gpu_speedup': statistics.median(fit_times['cpu']) / statistics.median(fit_times['gpu']),
               'max_scaled_prediction_error': fit_error, 'precision_pass': fit_error <= protocol['fit_prediction_tolerance'],
               'scope': 'initialization, group bootstrap, input conversion, 800 minibatch Adam updates, eval/sync; predictions outside fit clock'}
    if sources != {name: sha(ROOT / name) for name in sources} or load_training(ROOT)[1] != provenance:
        raise ValueError('measured sources or training evidence changed')
    ledger = args.out / 'predictions.jsonl.gz'
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as zipped:
        for observation in observations:
            zipped.write((json.dumps(observation, separators=(',', ':'), allow_nan=False) + '\n').encode())
    report = {'schema_version': 1, 'protocol': protocol, 'provenance': provenance, 'source_sha256': sources,
              'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'platform': platform.platform(), 'device': mx.device_info(), 'precision': 'strict float32, MLX_ENABLE_TF32=0',
              'dependencies': {name: importlib.metadata.version(name) for name in ('numpy', 'scipy', 'scikit-learn', 'mlx', 'mlx-metal')},
              'partitions': plans, 'fold_results': evidence, 'scoring': scoring, 'fitting': fitting,
              'prediction_rows': len(observations), 'prediction_ledger_sha256': sha(ledger),
              'dataset_sha256': sha(args.out / 'dataset.json'),
              'model_sha256': {p.name: sha(p) for p in sorted(args.out.glob('*.npz'))},
              'total_seconds': time.perf_counter() - begun, 'promotion': 'none', 'reserved_tests_measured': False,
              'limitations': ['latent bottleneck encodes explicit sampled features, not raw bytes',
                              '323 observed configs support prediction checks; these are not new encoder proposals',
                              'features come from the training slice of S5; no validation/test targets feed training or calibration',
                              'repeated config/case labels use median log paired ratios; clock/codegen noise remains',
                              'small grouped corpus and held configuration extrapolation do not establish distribution-free coverage',
                              'device timings are fitting/scoring components; whole-loop verified Bayesian search remains separate']}
    write_json(args.out / 'result.json', report)
    print('completed', args.out / 'result.json', flush=True)


if __name__ == '__main__':
    main()
