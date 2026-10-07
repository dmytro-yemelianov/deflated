#!/usr/bin/env python3
"""Serial verified MOTPE comparison with observed wall-time frontier curves."""
import argparse
import copy
import json
import pathlib
import platform
import statistics
import subprocess
import sys
import time

from search_campaign import hypervolume
from search_corpus import ROOT, validate
from search_cpu import select_finalists, source_files, write_json
from search_poc import sha


def curve(study, protocol):
    points = [protocol['hypervolume_anchor']]
    result = [{'seconds': 0.0, 'unique_evaluations': 0, 'hypervolume': hypervolume(points, protocol['hypervolume_reference'])}]
    for trial in study['training'][4:]:
        points.append([trial['aggregate']['time_vs_paired_balanced'], trial['aggregate']['size_vs_balanced']])
        seconds = trial['search_elapsed_seconds']
        if seconds <= result[-1]['seconds']:
            raise ValueError('search completion clock must increase')
        result.append({'seconds': seconds, 'unique_evaluations': len(result),
                       'hypervolume': hypervolume(points, protocol['hypervolume_reference'])})
    return result


def at_time(observed, seconds):
    if seconds > observed[-1]['seconds']:
        raise ValueError('cannot extrapolate a completed study')
    return next(row for row in reversed(observed) if row['seconds'] <= seconds)


def run(corpus, directory, protocol_path):
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads((corpus / 'manifest.json').read_text())
    validate(corpus, manifest)
    sources = {name: sha(ROOT / name) for name in source_files() + ['scripts/search_bayesian_campaign.py', 'scripts/search_bayesian_protocol.json']}
    protocol_hash, manifest_hash = sha(protocol_path), sha(corpus / 'manifest.json')
    metadata = {'protocol': protocol, 'protocol_sha256': protocol_hash, 'source_sha256': sources,
                'manifest_sha256': manifest_hash, 'corpus': manifest, 'platform': platform.platform(),
                'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'reserved_test_measured': False, 'promotion': 'none'}
    write_json(directory / 'provenance.json', metadata)
    schedule = [(strategy, seed) for index, seed in enumerate(protocol['seeds'])
                for strategy in protocol['strategies'][index:] + protocol['strategies'][:index]]
    write_json(directory / 'schedule.json', schedule)
    studies = []
    for index, (strategy, seed) in enumerate(schedule):
        out = directory / f'{index:02}-{strategy}-{seed}'
        print('study', index, strategy, seed, flush=True)
        command = [sys.executable, str(ROOT / 'scripts/search_cpu.py'), '--strategy', strategy,
                   '--seed', str(seed), '--trials', str(protocol['configured_trials']), '--rounds', str(protocol['training_rounds']),
                   '--min-ms', str(protocol['training_minimum_batch_ms']), '--trial-timeout', str(protocol['trial_timeout_seconds']),
                   '--training-only', '--corpus', str(corpus), '--out', str(out)]
        with (directory / f'{index:02}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, check=True)
        if sources != {name: sha(ROOT / name) for name in sources} or sha(protocol_path) != protocol_hash or sha(corpus / 'manifest.json') != manifest_hash:
            raise ValueError('frozen sources/protocol/corpus changed')
        study = json.loads((out / 'result.json').read_text())
        if len(study['training']) != protocol['configured_trials'] + 4 or study['validation_measured']:
            raise ValueError('wrong unique configured budget or unexpected validation')
        if len({trial['id'] for trial in study['training']}) != len(study['training']):
            raise ValueError('duplicate charged evaluations')
        study['curve'] = curve(study, protocol)
        overhead = study['optimizer_setup_seconds'] + study['proposal_seconds'] + (study['optimizer']['feedback_seconds'] if study['optimizer'] else 0)
        duration = study['curve'][-1]['seconds']
        study.update(directory=str(out.relative_to(ROOT)), optimizer_seconds=overhead,
                     search_seconds=duration, optimizer_fraction=overhead / duration,
                     instantaneous_optimizer_speedup_bound=duration / (duration - overhead))
        studies.append(study)
    if len({s['binary_sha256'] for s in studies}) != 1:
        raise ValueError('all strategies must use the same native binary')
    common = min(s['search_seconds'] for s in studies)
    checkpoints = [t for t in protocol['wall_time_checkpoints_seconds'] if t <= common]
    for study in studies:
        study['common_horizon'] = at_time(study['curve'], common)
        study['wall_checkpoints'] = {str(t): at_time(study['curve'], t) for t in checkpoints}
        study['time_to_targets'] = {str(target): next((r['seconds'] for r in study['curve'] if r['hypervolume'] >= target), None)
                                    for target in protocol['time_to_hypervolume']}
    by_config = {}
    for study in studies:
        for trial in study['training']:
            by_config.setdefault(trial['id'], []).append(trial)
    pooled = []
    for key, values in by_config.items():
        trial = copy.deepcopy(values[0])
        if len({v['aggregate']['packed_bytes'] for v in values}) != 1:
            raise ValueError('exact sizes differ across identical configurations')
        trial['aggregate']['time_vs_paired_balanced'] = statistics.median(v['aggregate']['time_vs_paired_balanced'] for v in values)
        pooled.append(trial)
    roles = select_finalists(pooled, .01)
    finalists = {'selection': 'training only; pooled median paired time, no validation feedback', 'roles': roles,
                 'configs': {t['id']: t['config'] for t in pooled if t['id'] in roles.values()}}
    write_json(directory / 'finalists.json', finalists)
    result = {**metadata, 'studies': studies, 'common_horizon_seconds': common, 'checkpoints_seconds': checkpoints,
              'finalists': finalists, 'finalists_sha256': sha(directory / 'finalists.json'),
              'total_seconds': time.perf_counter() - started,
              'limitations': ['equal unique budgets and wall checkpoints within observed runs; no extrapolation after study termination',
                              'three seeds are a bounded pilot; ranges must be retained, no significance claim',
                              'MOTPE uses log2 integer probes and conditional insertion; NSGA-II uses categorical values; domain is the same 880 configurations',
                              'shared compile and four-control costs precede search clocks and are reported separately',
                              'whole-loop clocks include oracle and source/corpus checks; encoder-only paired clocks remain separate',
                              'optimizer bound assumes all timed optimizer work vanished; it is not a GPU speedup measurement']}
    write_json(directory / 'result.json', result)
    print('completed', directory / 'result.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=pathlib.Path, default=ROOT / 'target/search/corpus-mixed-s2')
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_bayesian_protocol.json')
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    run(args.corpus.resolve(), args.out.resolve(), args.protocol.resolve())
