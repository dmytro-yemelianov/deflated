#!/usr/bin/env python3
"""Freeze first, then serial fresh warm/cold/decode/tiny/RSS/reference gates."""
import argparse
import copy
import hashlib
import json
import math
import os
import pathlib
import platform
import random
import re
import subprocess
import time

from search_corpus import ROOT, features, validate
from search_cpu import worker_method, write_json
from search_poc import decode_exact, sha


def sources():
    names = ['Cargo.toml', 'Cargo.lock', 'crates/deflate-core/Cargo.toml', 'lean-toolchain',
             'crates/deflate-core/examples/final_bench.rs', 'crates/deflate-core/examples/final_size.rs',
             'crates/deflate-core/examples/support/final_bench.rs', 'crates/deflate-core/examples/support/policy.rs',
             'scripts/search_final_campaign.py', 'scripts/search_final_protocol.json',
             'scripts/search_corpus.py', 'scripts/search_cpu.py', 'scripts/search_poc.py']
    names += [str(p.relative_to(ROOT)) for directory, pattern in [('crates/deflate-core/src', '*.rs'), ('spec', '*.lean')] for p in sorted((ROOT / directory).rglob(pattern))]
    return {name: sha(ROOT / name) for name in names}


def corpus(out, parents, protocol):
    out.mkdir(parents=True, exist_ok=False)
    records, seen = [], set()
    for parent_index, parent in enumerate(parents):
        meta = json.loads((parent / 'manifest.json').read_text())
        validate(parent, meta)
        for original in meta['cases']:
            if original['partition'] != 'test' or original['sha256'] in seen:
                continue
            seen.add(original['sha256'])
            case = copy.deepcopy(original)
            raw = (parent / case['path']).read_bytes()
            name = 'fresh-' + str(parent_index) + '-' + pathlib.PurePosixPath(case['path']).name
            case.update(path='test/' + name, scope='fresh', parent_manifest_sha256=sha(parent / 'manifest.json'))
            file = out / case['path']
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
            records.append(case)
    rng = random.Random(protocol['seed'])
    tiny_seen = set()
    for size in protocol['tiny_sizes']:
        for family, raw in (('tiny-random', rng.randbytes(size)), ('tiny-periodic', (b'abc' * (size // 3 + 1))[:size])):
            digest = hashlib.sha256(raw).hexdigest()
            if digest in tiny_seen:
                continue
            tiny_seen.add(digest)
            path = f'stress/{family}-{size}.raw'
            file = out / path
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
            records.append({'path': path, 'partition': 'stress', 'scope': 'tiny', 'family': family, 'regime': f'{family}:{size}',
                            'seed': protocol['seed'], 'params': {'bytes': size}, 'bytes': size, 'sha256': digest, 'features': features(raw)})
    meta = {'schema_version': 1, 'cases': records, 'parents': [{'path': str(p.relative_to(ROOT)), 'manifest_sha256': sha(p / 'manifest.json')} for p in parents],
            'policy': 'reserved test regimes only; no training/validation labels or adaptive selection'}
    write_json(out / 'manifest.json', meta)
    validate(out, meta)
    return meta


def freeze_methods(out, protocol):
    bayesian = json.loads((ROOT / 'scripts/reports/search-bayesian.json').read_text())
    policies = json.loads((ROOT / 'scripts/reports/search-policy.json').read_text())
    mixed = json.loads((ROOT / 'scripts/reports/search-mixed.json').read_text())
    methods = {name: {'worker': name, 'origin': 'predeclared production/reference control'} for name in protocol['controls']}
    for role, source_role in (('speed', 'speed'), ('compromise', 'balanced'), ('size', 'size')):
        key = bayesian['finalists']['roles'][source_role]
        config = bayesian['finalists']['configs'][key]
        methods['bayesian-' + role] = {'worker': worker_method(config), 'config': config, 'origin': 'S3 training-only frozen finalist'}
    for role in ('speed', 'size'):
        text = policies['native_policies'][role]
        path = out / ('policy-' + role + '.txt')
        path.write_text(text)
        if sha(path) != policies['policy_sha256'][role]:
            raise ValueError('S5 policy payload changed')
        methods['policy-' + role] = {'worker': 'policy@' + str(path), 'policy': text, 'policy_sha256': sha(path), 'origin': 'S5 grouped training-only frozen policy'}
    # S8 selected unchanged presets, already included above. A new mixed
    # finalist requires this driver to be explicitly extended before freezing.
    if any(mixed['finalists']['configs'][key]['method'] not in protocol['controls'] for key in mixed['finalists']['roles'].values()):
        raise ValueError('extend/freeze S9 driver for newly selected S8 method')
    write_json(out / 'finalists.json', {'methods': methods, 'roles': protocol['roles'],
               'selection_sha256': {name: sha(ROOT / f'scripts/reports/search-{name}.json') for name in ('bayesian', 'policy', 'mixed')},
               'selection': 'no fresh/tiny/RSS feedback; retain every frozen role and predeclared control'})
    return methods


def parse_rss(text, system):
    pattern = r'(\d+)\s+maximum resident set size' if system == 'Darwin' else r'Maximum resident set size \(kbytes\):\s*(\d+)'
    found = re.search(pattern, text)
    if not found:
        raise ValueError('no process peak RSS measurement')
    return int(found[1]) * (1 if system == 'Darwin' else 1024)


def schedule(session, original_case_index, names):
    offset = (session + original_case_index) % len(names)
    return [(name, (session + original_case_index + names.index(name)) % 2)
            for name in names[offset:] + names[:offset]]


def run(out, protocol_path):
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    protocol = json.loads(protocol_path.read_text())
    methods = freeze_methods(out, protocol)
    meta = corpus(out / 'corpus', [ROOT / 'target/search/corpus-policy-s5-final', ROOT / 'target/search/corpus-extended-s7-checked'], protocol)
    frozen, freeze, manifest_hash, protocol_hash = sources(), sha(out / 'finalists.json'), sha(out / 'corpus/manifest.json'), sha(protocol_path)
    compiler = subprocess.check_output(['rustc', '--version'], text=True).strip()
    flags = {k: v for k, v in os.environ.items() if k.startswith('CARGO_PROFILE_') or k in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')}
    key = hashlib.sha256(json.dumps([frozen, compiler, flags, freeze], sort_keys=True).encode()).hexdigest()[:20]
    target = ROOT / 'target/search/final-builds' / key
    subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'deflate-core', '--example', 'final_bench', '--features', 'research-tuning', '--target-dir', str(target)], cwd=ROOT, check=True)
    binary = target / 'release/examples/final_bench'
    binary_hash = sha(binary)
    probe_input = out / 'private-probe.raw'
    probe_rng = random.Random(protocol['seed'] + 1)
    probe_pattern = probe_rng.randbytes(8191)
    probe_raw = (probe_pattern * 5) + b'abc' * 4096
    probe_input.write_bytes(probe_raw)
    # Build every linked-size probe before any measured timing. These are
    # standalone prototype probes, not claimed production integration sizes.
    size_builds = {}
    for name, method in methods.items():
        size_builds[name] = {}
        expected_out = out / 'probe-expected'
        subprocess.check_output([str(binary), 'cold', str(probe_input), str(expected_out), '1', method['worker'], '0'])
        expected_packet = (expected_out / 'candidate.deflate').read_bytes()
        decode_exact(expected_packet, probe_raw)
        for profile in ('release', 'min'):
            probe_target = ROOT / 'target/search/final-size-builds' / key / name / profile
            print('size build', name, profile, flush=True)
            subprocess.run(['cargo', 'build', '--locked', '--profile', profile, '-p', 'deflate-core', '--example', 'final_size', '--features', 'research-tuning', '--target-dir', str(probe_target)],
                           cwd=ROOT, env={**os.environ, 'DEFLATED_FINAL_METHOD': method['worker']}, check=True)
            probe = probe_target / profile / 'examples/final_size'
            probe_packet = out / 'probe.deflate'
            subprocess.check_output([str(probe), str(probe_input), str(probe_packet)])
            if probe_packet.read_bytes() != expected_packet:
                raise ValueError('linked-size probe encodes a different method')
            policy_bytes = len(method.get('policy', '').encode())
            size_builds[name][profile] = {'binary_path': str(probe.relative_to(ROOT)), 'binary_sha256': sha(probe), 'binary_bytes': probe.stat().st_size,
                                         'external_policy_bytes': policy_bytes, 'total_bytes': probe.stat().st_size + policy_bytes,
                                         'probe_raw_sha256': sha(probe_input), 'probe_packet_sha256': sha(probe_packet)}
    write_json(out / 'size-builds.json', size_builds)
    def guard():
        if sources() != frozen or sha(binary) != binary_hash or sha(out / 'finalists.json') != freeze or sha(out / 'corpus/manifest.json') != manifest_hash or sha(protocol_path) != protocol_hash:
            raise ValueError('frozen final study changed')
        for method in methods.values():
            if 'policy' in method and sha(pathlib.Path(method['worker'].removeprefix('policy@'))) != method['policy_sha256']:
                raise ValueError('frozen policy changed')
        validate(out / 'corpus', meta)
    temporary = out / 'current-streams'
    first = {}
    rows = []
    names = list(methods)
    cases = meta['cases']
    def call(mode, case, method, order):
        raw_path = out / 'corpus' / case['path']
        minimum = protocol['tiny_minimum_batch_ms' if case['scope'] == 'tiny' else 'warm_minimum_batch_ms']
        row = json.loads(subprocess.check_output([str(binary), mode, str(raw_path), str(temporary), str(minimum), method, str(order)], text=True, timeout=120))
        raw = raw_path.read_bytes()
        for suffix in ('candidate', 'baseline') if mode == 'warm' else ('candidate',):
            packet = (temporary / (suffix + '.deflate')).read_bytes()
            decode_exact(packet, raw)
            field = 'packed_bytes' if suffix == 'candidate' else 'baseline_bytes'
            if len(packet) != row[field] or row['raw_bytes'] != len(raw):
                raise ValueError('final packet size differs')
            row['packed_sha256' if suffix == 'candidate' else 'baseline_packed_sha256'] = hashlib.sha256(packet).hexdigest()
        for field in ('encode_ns', 'decode_ns'):
            if not math.isfinite(row[field]) or row[field] <= 0:
                raise ValueError('invalid final timing')
        return row
    current = {'phase': 'timing'}
    try:
        with (out / 'measurements.jsonl').open('w') as log:
            for session in range(protocol['sessions']):
                print('session', session, flush=True)
                for case_index, case in enumerate(cases[session % len(cases):] + cases[:session % len(cases)]):
                    original_case_index = (case_index + session % len(cases)) % len(cases)
                    for index, (name, order) in enumerate(schedule(session, original_case_index, names)):
                        current = {'phase': 'timing', 'session': session, 'input': case['path'], 'method': name}
                        warm = call('warm', case, methods[name]['worker'], order)
                        cold = {}
                        for turn in range(2):
                            side = (order + turn) % 2
                            cold[side] = call('cold', case, methods[name]['worker'] if side == 0 else 'balanced', 0)
                        if cold[0]['packed_sha256'] != warm['packed_sha256'] or cold[1]['packed_sha256'] != warm['baseline_packed_sha256']:
                            raise ValueError('warm/cold output differs')
                        hashes = (warm['packed_sha256'], warm['baseline_packed_sha256'])
                        if first.setdefault((name, case['path']), hashes) != hashes:
                            raise ValueError('final session output changed')
                        row = {**warm, 'session': session, 'method': name, 'input': case['path'], 'scope': case['scope'],
                               'method_order': index, 'pair_order': order, 'original_case_index': original_case_index,
                               'cold_encode_ns': cold[0]['encode_ns'], 'cold_decode_ns': cold[0]['decode_ns'],
                               'cold_baseline_encode_ns': cold[1]['encode_ns'], 'cold_baseline_decode_ns': cold[1]['decode_ns']}
                        rows.append(row)
                        log.write(json.dumps(row, allow_nan=False) + '\n')
                        log.flush()
                guard()
        # Separate whole-process peak RSS runs after every timing session.
        largest_fresh = max((c for c in cases if c['scope'] == 'fresh'), key=lambda c: c['bytes'])
        largest_real = max((c for c in cases if c['family'] == 'real'), key=lambda c: c['bytes'])
        old_root = ROOT / 'target/search/corpus-mixed-s2'
        old_meta = json.loads((old_root / 'manifest.json').read_text())
        large_old = max((c for c in old_meta['cases'] if c['family'] == 'real'), key=lambda c: c['bytes'])
        memory_cases = [{'path': str((out / 'corpus' / c['path']).relative_to(ROOT)), 'sha256': c['sha256'], 'bytes': c['bytes'], 'scope': 'fresh-memory'} for c in (largest_fresh, largest_real)]
        memory_cases.append({'path': str((old_root / large_old['path']).relative_to(ROOT)), 'sha256': large_old['sha256'], 'bytes': large_old['bytes'], 'scope': 'previous-full-file-memory-only'})
        rss = []
        system = platform.system()
        for case in memory_cases:
            if sha(ROOT / case['path']) != case['sha256']:
                raise ValueError('memory input changed')
            for name, method in methods.items():
                for repeat in range(protocol['rss_repeats']):
                    print('rss', name, case['bytes'], repeat, flush=True)
                    current = {'phase': 'RSS', 'method': name, 'input': case['path'], 'repeat': repeat}
                    packet = out / 'memory.deflate'
                    command = ['/usr/bin/time', '-l' if system == 'Darwin' else '-v', str(binary), '--memory', str(ROOT / case['path']), str(packet), method['worker']]
                    run = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)
                    decode_exact(packet.read_bytes(), (ROOT / case['path']).read_bytes())
                    rss.append({'method': name, 'case': case, 'repeat': repeat, 'peak_rss_bytes': parse_rss(run.stderr, system),
                                'packed_sha256': sha(packet), 'native': json.loads(run.stdout), 'time_stderr': run.stderr})
        guard()
        write_json(out / 'result.json', {'protocol': protocol, 'protocol_sha256': protocol_hash, 'source_sha256': frozen, 'finalists_sha256': freeze,
                   'finalists': json.loads((out / 'finalists.json').read_text()), 'corpus': meta, 'manifest_sha256': manifest_hash,
                   'binary_path': str(binary.relative_to(ROOT)), 'binary_sha256': binary_hash, 'size_builds': size_builds,
                   'rss': rss, 'rows': rows, 'verified_rows': len(rows), 'platform': platform.platform(), 'machine': platform.machine(),
                   'cpu': subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip() if system == 'Darwin' else platform.processor(),
                   'rustc': compiler, 'build_overrides': flags, 'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                   'total_seconds': time.perf_counter() - started, 'adaptive_test_feedback': False, 'promotion': 'pending evidence analysis'})
        print('completed', out / 'result.json', flush=True)
    except BaseException as error:
        write_json(out / 'failure.json', {**current, 'error': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_final_protocol.json')
    args = parser.parse_args()
    run(args.out.resolve(), args.protocol.resolve())
