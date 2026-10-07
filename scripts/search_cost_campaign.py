#!/usr/bin/env python3
"""Exact short costs and serial bounded-parser/compiled-geometry evaluation."""
import argparse
import copy
import hashlib
import json
import pathlib
import random
import subprocess
import time

from search_corpus import ROOT, features, validate
from search_cost_build import build, sources
from search_cost_oracle import exact, longest
from search_cpu import aggregate, validate_measurements, write_json
from search_poc import decode_exact, sha


def corpus(base, extensions, out, chunk_bytes):
    records, payloads = [], {}
    manifests = []
    for root, prefix in ((base, 'previous-'), (extensions, 'extended-')):
        meta = json.loads((root / 'manifest.json').read_text())
        validate(root, meta)
        manifests.append({'path': str(root.relative_to(ROOT)), 'sha256': sha(root / 'manifest.json')})
        for original in meta['cases']:
            if original['partition'] == 'stress':
                continue
            case = copy.deepcopy(original)
            raw = (root / case['path']).read_bytes()
            source_sha = hashlib.sha256(raw).hexdigest()
            start = (len(raw) - chunk_bytes) // 2 if len(raw) > chunk_bytes and case['partition'] != 'test' else 0
            if case['partition'] != 'test':
                raw = raw[start:start + chunk_bytes]
            case.update(path=case['partition'] + '/' + prefix + pathlib.PurePosixPath(case['path']).name,
                        dataset=prefix.removesuffix('-'), source_payload_sha256=source_sha, source_range=[start, len(raw)],
                        bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), features=features(raw))
            records.append(case)
            payloads[case['path']] = raw
    meta = {'schema_version': 1, 'chunk_bytes': chunk_bytes, 'parents': manifests, 'cases': records,
            'generator_sha256': sha(pathlib.Path(__file__)), 'test_policy': 'copied/hashed only; never encoded here'}
    out.mkdir(parents=True, exist_ok=False)
    for path, raw in payloads.items():
        file = out / path
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(raw)
    write_json(out / 'manifest.json', meta)
    validate(out, meta)
    return meta


def run(base, extensions, out, protocol_path):
    out.mkdir(parents=True, exist_ok=False)
    begun = time.perf_counter()
    protocol = json.loads(protocol_path.read_text())
    extended_meta = json.loads((extensions / 'manifest.json').read_text())
    if extended_meta['generator_sha256'] != sha(ROOT / 'scripts/search_extended_corpus.py'):
        raise ValueError('regenerate extensions for current generator')
    if any(sha(ROOT / name) != digest for name, digest in extended_meta['helper_sha256'].items()):
        raise ValueError('regenerate extensions for current hash-function helpers')
    corpus_root = out / 'corpus'
    meta = corpus(base, extensions, corpus_root, protocol['cost_chunk_bytes'])
    layouts = {json.dumps(layout, sort_keys=True): layout for layout in protocol['geometry']}
    default = {'hash_bits': 15, 'window_bytes': 32768}
    layouts.setdefault(json.dumps(default, sort_keys=True), default)
    binaries, builds = {}, {}
    for key, layout in layouts.items():
        print('build', layout, flush=True)
        binary, build_meta = build(layout)
        binaries[key], builds[key] = binary, build_meta
    main_binary = binaries[json.dumps(default, sort_keys=True)]
    frozen = {**sources(), **{name: sha(ROOT / name) for name in (
        'scripts/search_cost_campaign.py', 'scripts/search_cost_oracle.py', 'scripts/search_cost_protocol.json',
        'scripts/search_extended_corpus.py', 'scripts/search_corpus.py', 'scripts/search_cpu.py', 'scripts/search_poc.py')}}
    protocol_hash, manifest_hash = sha(protocol_path), sha(corpus_root / 'manifest.json')
    def guard():
        if frozen != {name: sha(ROOT / name) for name in frozen} or sha(protocol_path) != protocol_hash or sha(corpus_root / 'manifest.json') != manifest_hash:
            raise ValueError('frozen parser sources/protocol/corpus changed')
        for key, binary in binaries.items():
            if sha(binary) != builds[key]['binary_sha256']:
                raise ValueError('compiled geometry binary changed')
        validate(corpus_root, meta)
    # Frozen random recipes: no searching for a preferred counterexample.
    rng, exact_rows = random.Random(protocol['seed']), []
    short = out / 'oracle.raw'
    for index in range(protocol['exact_cases']):
        raw = bytearray(rng.choice((0, 1, 2, 144, 255)) for _ in range(64 + index % 65))
        if index % 2:
            pos = len(raw) // 2
            distance = rng.randint(1, pos)
            for j in range(rng.randint(3, min(32, len(raw) - pos))):
                raw[pos + j] = raw[pos + j - distance]
        raw = bytes(raw)
        short.write_bytes(raw)
        expected, greedy = exact(raw), longest(raw)
        native = json.loads(subprocess.check_output([str(main_binary), '--tokens', str(short), 'exact'], text=True))
        if native['fixed_bits'] != expected['fixed_bits'] or native['packed_bytes'] != expected['packed_bytes']:
            raise ValueError('exact native bits differ from independent oracle')
        decode_exact(bytes.fromhex(native['packed_hex']), raw)
        exact_rows.append({'id': index, 'raw_hex': raw.hex(), 'oracle': expected, 'greedy': greedy, 'native': native})
    write_json(out / 'exact-oracle.json', exact_rows)
    configs = []
    for method in protocol['methods']:
        configs.append({'method': method} if method in ('balanced', 'best', 'fast') else {'method': method, 'layout': default})
    configs += [{'method': protocol['geometry_method'], 'layout': layout} for layout in layouts.values()]
    configs = list({json.dumps(c, sort_keys=True): c for c in configs}.values())
    measured = []
    def measure(config, partition, rounds):
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        binary = binaries[json.dumps(config.get('layout', default), sort_keys=True)]
        directory = out / partition / key
        directory.mkdir(parents=True, exist_ok=False)
        print(partition, config, flush=True)
        started = time.perf_counter()
        cases = [c for c in meta['cases'] if c['partition'] == partition]
        try:
            with (directory / 'measurements.jsonl').open('w') as log, (directory / 'stderr.log').open('w') as err:
                subprocess.run([str(binary), str(corpus_root / partition), str(directory / 'streams'), str(rounds),
                                str(protocol['minimum_batch_ms']), config['method']], stdout=log, stderr=err, timeout=1200, check=True)
            rows = [json.loads(line) for line in (directory / 'measurements.jsonl').read_text().splitlines()]
            validate_measurements(rows, cases, directory / 'streams', rounds, corpus_root, True)
            guard()
            result = {'id': key, 'config': config, 'partition': partition, 'rows': rows, 'aggregate': aggregate(rows),
                      'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in rows),
                      'elapsed_seconds': time.perf_counter() - started}
            write_json(directory / 'result.json', result)
            measured.append(result)
            return result
        except BaseException as error:
            write_json(directory / 'failure.json', {'config': config, 'partition': partition, 'error': str(error)})
            raise
    training = [measure(config, 'train', protocol['training_rounds']) for config in configs]
    bounds = protocol['guardrails']
    eligible = [m for m in training if not m['config']['method'].endswith(':fixed') and m['max_file_size_vs_balanced'] <= bounds['maximum_file_size_vs_balanced']]
    roles = {'speed': min([m for m in eligible if m['aggregate']['size_vs_balanced'] <= bounds['speed_aggregate_size_vs_balanced']], key=lambda m: m['aggregate']['time_vs_paired_balanced'])['id'],
             'size': min(eligible, key=lambda m: (m['aggregate']['packed_bytes'], m['aggregate']['time_vs_paired_balanced']))['id'],
             'balanced': min([m for m in eligible if m['aggregate']['size_vs_balanced'] <= bounds['compromise_aggregate_size_vs_balanced']], key=lambda m: m['aggregate']['time_vs_paired_balanced'])['id']}
    sentinels = {m['id'] for m in training if m['config']['method'] in protocol['methods']}
    finalist_ids = sorted(set(roles.values()) | sentinels)
    selected = {'roles': roles, 'configs': {m['id']: m['config'] for m in training if m['id'] in finalist_ids},
                'selection': 'training only; default parser/fixed/production controls retained as sentinels even if slower'}
    write_json(out / 'finalists.json', selected)
    final_hash = sha(out / 'finalists.json')
    validation = [measure(selected['configs'][key], 'validation', protocol['validation_rounds']) for key in finalist_ids]
    if sha(out / 'finalists.json') != final_hash:
        raise ValueError('frozen parser finalists changed')
    guard()
    write_json(out / 'result.json', {'protocol': protocol, 'protocol_sha256': protocol_hash, 'source_sha256': frozen,
               'git_parent_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'corpus': meta, 'manifest_sha256': manifest_hash, 'builds': builds, 'exact_rows': exact_rows,
               'training': training, 'validation': validation, 'finalists': selected, 'finalists_sha256': final_hash,
               'verified_rows': sum(len(m['rows']) for m in measured), 'reserved_tests_encoded': False,
               'total_seconds': time.perf_counter() - begun, 'promotion': 'none'})
    print('completed', out / 'result.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=pathlib.Path, default=ROOT / 'target/search/corpus-mixed-s2')
    parser.add_argument('--extensions', type=pathlib.Path, default=ROOT / 'target/search/corpus-extended-s7-checked')
    parser.add_argument('--protocol', type=pathlib.Path, default=ROOT / 'scripts/search_cost_protocol.json')
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    run(args.base.resolve(), args.extensions.resolve(), args.out.resolve(), args.protocol.resolve())
