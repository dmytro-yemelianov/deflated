#!/usr/bin/env python3
"""Serial S8 native comparison with frozen roles and retained format witnesses."""
import argparse
import hashlib
import json
import os
import pathlib
import random
import subprocess
import time

from search_corpus import ROOT, validate
from search_cpu import aggregate, validate_measurements, write_json
from search_poc import decode_exact, sha


def sources():
    names = ['Cargo.toml', 'Cargo.lock', 'crates/deflate-core/Cargo.toml',
             'crates/deflate-core/examples/mixed_blocks.rs', 'crates/deflate-core/examples/support/mixed_blocks.rs',
             'scripts/search_mixed_campaign.py', 'scripts/search_mixed_protocol.json',
             'scripts/search_corpus.py', 'scripts/search_cpu.py', 'scripts/search_poc.py']
    names += [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'crates/deflate-core/src').rglob('*.rs'))]
    return {name: sha(ROOT / name) for name in names}


def build():
    compiler = subprocess.check_output(['rustc', '--version'], text=True).strip()
    flags = {name: value for name, value in os.environ.items() if name.startswith('CARGO_PROFILE_RELEASE_') or name in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')}
    frozen = sources()
    key = hashlib.sha256(json.dumps([frozen, compiler, flags], sort_keys=True).encode()).hexdigest()[:20]
    target = ROOT / 'target/search/mixed-builds' / key
    subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'deflate-core', '--example', 'mixed_blocks', '--target-dir', str(target)], cwd=ROOT, check=True)
    binary = target / 'release/examples/mixed_blocks'
    return binary, {'rustc': compiler, 'build_overrides': flags, 'binary_path': str(binary.relative_to(ROOT)), 'binary_sha256': sha(binary), 'source_sha256': frozen}


def run(corpus, out, protocol_path):
    out.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter()
    protocol = json.loads(protocol_path.read_text())
    meta = json.loads((corpus / 'manifest.json').read_text())
    validate(corpus, meta)
    frozen_manifest = sha(corpus / 'manifest.json')
    frozen_protocol = sha(protocol_path)
    binary, provenance = build()
    def guard():
        if sources() != provenance['source_sha256'] or sha(binary) != provenance['binary_sha256'] or sha(protocol_path) != frozen_protocol or sha(corpus / 'manifest.json') != frozen_manifest:
            raise ValueError('frozen mixed-emission inputs changed')
        validate(corpus, meta)
    rng = random.Random(protocol['seed'])
    raws = [b'', b'\x90', bytes(range(256)), rng.randbytes(1024),
            rng.randbytes(1024) + b'x' * 8192,
            rng.randbytes(2048) + b'abc' * 4096 + rng.randbytes(1024)]
    witnesses = []
    path = out / 'witness.raw'
    for index, raw in enumerate(raws):
        path.write_bytes(raw)
        for method in ('compressed:balanced:1024', 'mixed:balanced:1024', 'mixed:balanced:4096', 'mixed:balanced:16384', 'mixed:fast:1024', 'mixed:best:1024'):
            record = json.loads(subprocess.check_output([str(binary), '--inspect', str(path), method], text=True))
            decode_exact(bytes.fromhex(record['packed_hex']), raw)
            witnesses.append({'input_id': index, 'raw_hex': raw.hex(), 'method': method, **record})
    write_json(out / 'witnesses.json', witnesses)
    methods = [f'{emission}:{level}:{limit}' for emission in protocol['emissions'] for level in protocol['levels'] for limit in protocol['token_limits']] + protocol['levels']
    def measure(method, partition, rounds):
        config = {'method': method}
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        directory = out / partition / key
        directory.mkdir(parents=True, exist_ok=False)
        print(partition, method, flush=True)
        started = time.perf_counter()
        cases = [c for c in meta['cases'] if c['partition'] == partition]
        try:
            with (directory / 'measurements.jsonl').open('w') as log, (directory / 'stderr.log').open('w') as err:
                subprocess.run([str(binary), str(corpus / partition), str(directory / 'streams'), str(rounds), str(protocol['minimum_batch_ms']), method], stdout=log, stderr=err, timeout=1200, check=True)
            rows = [json.loads(line) for line in (directory / 'measurements.jsonl').read_text().splitlines()]
            validate_measurements(rows, cases, directory / 'streams', rounds, corpus, True)
            guard()
            event = {'id': key, 'config': config, 'partition': partition, 'rows': rows, 'aggregate': aggregate(rows),
                     'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in rows), 'elapsed_seconds': time.perf_counter() - started}
            write_json(directory / 'result.json', event)
            return event
        except BaseException as error:
            write_json(directory / 'failure.json', {'method': method, 'partition': partition, 'error': str(error)})
            raise
    training = [measure(method, 'train', protocol['training_rounds']) for method in methods]
    bounds = protocol['guardrails']
    eligible = [e for e in training if e['max_file_size_vs_balanced'] <= bounds['maximum_file_size_vs_balanced']]
    roles = {'speed': min([e for e in eligible if e['aggregate']['size_vs_balanced'] <= bounds['speed_aggregate_size_vs_balanced']], key=lambda e: e['aggregate']['time_vs_paired_balanced'])['id'],
             'compromise': min([e for e in eligible if e['aggregate']['size_vs_balanced'] <= bounds['compromise_aggregate_size_vs_balanced']], key=lambda e: e['aggregate']['time_vs_paired_balanced'])['id'],
             'size': min(eligible, key=lambda e: (e['aggregate']['packed_bytes'], e['aggregate']['time_vs_paired_balanced']))['id']}
    finalists = {'roles': roles, 'configs': {e['id']: e['config'] for e in training}, 'selection': protocol['selection']}
    write_json(out / 'finalists.json', finalists)
    freeze = sha(out / 'finalists.json')
    validation = [measure(method, 'validation', protocol['validation_rounds']) for method in methods]
    guard()
    if sha(out / 'finalists.json') != freeze:
        raise ValueError('mixed-emission selection changed')
    write_json(out / 'result.json', {'protocol': protocol, 'protocol_sha256': frozen_protocol, 'build': provenance,
               'source_sha256': provenance['source_sha256'], 'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'corpus_path': str(corpus.relative_to(ROOT)), 'corpus': meta, 'manifest_sha256': frozen_manifest,
               'witnesses': witnesses, 'finalists': finalists, 'finalists_sha256': freeze, 'training': training, 'validation': validation,
               'verified_rows': sum(len(e['rows']) for e in training + validation), 'reserved_tests_encoded': False,
               'total_seconds': time.perf_counter() - began, 'promotion': 'none'})
    print('completed', out / 'result.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=pathlib.Path, default=ROOT / 'target/search/cost-s7-full/corpus')
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_mixed_protocol.json')
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    run(args.corpus.resolve(), args.out.resolve(), args.protocol.resolve())
