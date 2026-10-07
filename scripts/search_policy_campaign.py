#!/usr/bin/env python3
"""Serial S5 measurement, nested fitting, frozen native-policy validation."""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import pathlib
import platform
import statistics
import subprocess
import time
import uuid

from search_campaign import confidence
from search_corpus import ROOT, validate
from search_cpu import aggregate, canonical, identity, source_files, validate_measurements, worker_method, write_json
from search_poc import decode_exact, sha
from search_policy import choose, features, nested, serialize


def run(corpus, out, protocol_path):
    protocol = json.loads(protocol_path.read_text())
    meta = json.loads((corpus / 'manifest.json').read_text())
    validate(corpus, meta)
    if meta['feature_source_sha256'] != sha(ROOT / 'scripts/search_policy.py') or meta['generator_sha256'] != sha(ROOT / 'scripts/search_policy_corpus.py'):
        raise ValueError('regenerate corpus for the current feature/generator sources')
    configs = protocol['vocabulary']
    if configs[0] != {'preset': 'balanced'} or len({identity(c) for c in configs}) != len(configs):
        raise ValueError('vocabulary must start with Balanced and contain unique canonical configs')
    for config in configs:
        canonical(config)
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    names = source_files() + ['scripts/search_policy.py', 'scripts/search_policy_corpus.py',
                             'scripts/search_policy_campaign.py', 'scripts/search_policy_protocol.json']
    sources = {name: sha(ROOT / name) for name in names}
    manifest_hash, protocol_hash = sha(corpus / 'manifest.json'), sha(protocol_path)
    rustc = subprocess.check_output(['rustc', '--version'], text=True).strip()
    overrides = {k: v for k, v in os.environ.items() if k.startswith('CARGO_PROFILE_RELEASE_') or k in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')}
    cpu = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip() if platform.system() == 'Darwin' else platform.processor()
    build_key = hashlib.sha256(json.dumps([sources, rustc, overrides], sort_keys=True).encode()).hexdigest()[:16]
    target = ROOT / 'target/search/policy-builds' / build_key
    provenance = {'source_sha256': sources, 'manifest_sha256': manifest_hash, 'protocol_sha256': protocol_hash,
                  'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  'rustc': rustc, 'cpu': cpu, 'platform': platform.platform(), 'python': platform.python_version(),
                  'build_overrides': overrides, 'protocol': protocol, 'corpus': meta, 'promotion': 'none',
                  'test_partition_measured': False}
    write_json(out / 'provenance.json', provenance)
    subprocess.run(['cargo', 'build', '-p', 'deflate-core', '--example', 'tune_config', '--features',
                    'research-tuning', '--release', '--target-dir', str(target)], cwd=ROOT, check=True)
    binary = target / 'release/examples/tune_config'
    binary_hash = sha(binary)
    provenance.update(binary_sha256=binary_hash, binary_path=str(binary.relative_to(ROOT)),
                      build_seconds=time.perf_counter() - started)
    write_json(out / 'provenance.json', provenance)
    cases_by_partition = {partition: [c for c in meta['cases'] if c['partition'] == partition]
                          for partition in ('train', 'validation')}
    def guard():
        if sources != {name: sha(ROOT / name) for name in sources} or sha(binary) != binary_hash or sha(protocol_path) != protocol_hash or sha(corpus / 'manifest.json') != manifest_hash:
            raise ValueError('measured sources/binary/protocol/manifest changed')
        validate(corpus, meta)
    # Cross-language checks are outside timing. Reserved cases are not encoded.
    for case in cases_by_partition['train'] + cases_by_partition['validation']:
        raw = (corpus / case['path']).read_bytes()
        native = json.loads(subprocess.check_output([str(binary), '--features', str(corpus / case['path'])], text=True))
        if native != features(raw) or native != case['policy_features']:
            raise ValueError('native/Python/manifest feature disagreement')
    events = []
    def measure(label, method, partition, rounds, minimum):
        directory = out / label
        directory.mkdir(parents=True)
        print(label, method, flush=True)
        begun = time.perf_counter()
        event = {'label': label, 'method': method, 'partition': partition}
        try:
            with (directory / 'measurements.jsonl').open('w') as log, (directory / 'stderr.log').open('w') as err:
                subprocess.run([str(binary), str(corpus / partition), str(directory / 'streams'),
                                str(rounds), str(minimum), method, 'balanced'], stdout=log, stderr=err,
                               timeout=600, check=True)
            rows = [json.loads(line) for line in (directory / 'measurements.jsonl').read_text().splitlines()]
            validate_measurements(rows, cases_by_partition[partition], directory / 'streams', rounds, corpus, True)
            guard()
            result = {**event, 'status': 'complete', 'rows': rows, 'aggregate': aggregate(rows),
                      'elapsed_seconds': time.perf_counter() - begun}
            write_json(directory / 'result.json', result)
            events.append(result)
            return result
        except BaseException as error:
            write_json(directory / 'failure.json', {**event, 'status': 'failed', 'error': str(error),
                                                   'elapsed_seconds': time.perf_counter() - begun})
            raise
    matrix_results = [measure('training/' + identity(c), worker_method(c), 'train',
                              protocol['training_rounds'], protocol['training_minimum_batch_ms']) for c in configs]
    row_maps = [{r['input']: r for r in measured['rows']} for measured in matrix_results]
    matrix = []
    for case in cases_by_partition['train']:
        name = pathlib.PurePosixPath(case['path']).name
        rows = [mapping[name] for mapping in row_maps]
        if len({r['baseline_bytes'] for r in rows}) != 1:
            raise ValueError('nondeterministic training baseline')
        base_ns = statistics.median(statistics.median(r['baseline_samples_ns']) for r in rows)
        matrix.append({'id': case['path'], 'group': ('real:' + case['source_file']) if case['family'] == 'real' else 'synthetic:' + case['family'],
                       'features': case['policy_features'], 'raw_bytes': case['bytes'],
                       'baseline_bytes': rows[0]['baseline_bytes'], 'baseline_ns': base_ns,
                       'measurements': [{'packed_bytes': r['packed_bytes'],
                                         'encode_ns': statistics.median(r['samples_ns']) / statistics.median(r['baseline_samples_ns']) * base_ns,
                                         'native_encode_ns': statistics.median(r['samples_ns']),
                                         'packed_sha256': r['packed_sha256']} for r in rows]})
    write_json(out / 'training-matrix.json', matrix)
    fitted = {}
    methods = [worker_method(c) for c in configs]
    for role, tolerance in protocol['roles'].items():
        print('nested-fit', role, flush=True)
        fitted[role] = nested(matrix, role, tolerance, protocol)
        (out / (role + '.policy')).write_text(serialize(fitted[role]['tree'], methods))
    write_json(out / 'frozen-policies.json', fitted)
    frozen_hash = sha(out / 'frozen-policies.json')
    policy_hashes = {role: sha(out / (role + '.policy')) for role in fitted}
    validations = []
    for role in fitted:
        result = measure('validation/policy-' + role, 'policy@' + str(out / (role + '.policy')), 'validation',
                         protocol['validation_rounds'], protocol['validation_minimum_batch_ms'])
        result['role'] = role
        # Verify serialized native policy choices against independently encoded leaves.
        for case, row in zip(sorted(cases_by_partition['validation'], key=lambda c: c['path']), result['rows']):
            if pathlib.PurePosixPath(case['path']).name != row['input']:
                raise ValueError('validation case order mismatch')
            index = choose(fitted[role]['tree'], {'raw_bytes': case['bytes'], 'features': case['policy_features']})
            expected = out / 'validation' / ('expected-' + role + '.deflate')
            subprocess.run([str(binary), '--memory', str(corpus / case['path']), str(expected), methods[index]],
                           stdout=subprocess.DEVNULL, timeout=600, check=True)
            if sha(expected) != row['packed_sha256']:
                raise ValueError('native policy choice differs from Python/serialized tree')
        for scope, subset in [('real-regression', [c for c in cases_by_partition['validation'] if c['family'] == 'real' and c['dataset'] == 'previous-regression']),
                              ('real-fresh', [c for c in cases_by_partition['validation'] if c['family'] == 'real' and c['dataset'] == 'fresh-calgary']),
                              ('synthetic-regression', [c for c in cases_by_partition['validation'] if c['family'] != 'real' and c['dataset'] == 'previous-regression']),
                              ('synthetic-fresh', [c for c in cases_by_partition['validation'] if c['dataset'] == 'fresh-synthetic'])]:
            names = {pathlib.PurePosixPath(c['path']).name for c in subset}
            selected = [r for r in result['rows'] if r['input'] in names]
            result[scope] = {'aggregate': aggregate(selected), 'confidence': confidence(selected, subset, 2000, protocol['cv_seed'] + 2),
                             'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in selected)}
        validations.append(result)
        if sha(out / 'frozen-policies.json') != frozen_hash or policy_hashes != {r: sha(out / (r + '.policy')) for r in fitted}:
            raise ValueError('frozen policy changed during validation')
    controls = [measure('validation/control-' + c['preset'], worker_method(c), 'validation',
                        protocol['validation_rounds'], protocol['validation_minimum_batch_ms']) for c in configs[:3]]
    guard()
    write_json(out / 'result.json', {**provenance, 'matrix': matrix, 'fitted': fitted, 'frozen_sha256': frozen_hash,
                                   'policy_sha256': policy_hashes, 'validation': validations, 'controls': controls,
                                   'events': events, 'total_seconds': time.perf_counter() - started,
                                   'verified_rows': sum(len(e['rows']) for e in events)})
    print('completed', out / 'result.json', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=pathlib.Path, required=True)
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_policy_protocol.json')
    parser.add_argument('--out', type=pathlib.Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    out = args.out or ROOT / 'target/search/policies' / stamp
    run(args.corpus.resolve(), out.resolve(), args.protocol.resolve())


if __name__ == '__main__':
    main()
