#!/usr/bin/env python3
"""After performance runs, replay new packets through the actual Lean decoder."""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

from search_corpus import ROOT
from search_poc import decode_exact, sha

sys.path.insert(0, str(ROOT / 'oracles'))
from differential import LEAN, RUST, run_oracle


def run(directory):
    result = json.loads((directory / 'result.json').read_text()) if directory else None
    if result and (sha(ROOT / result['binary_path']) != result['binary_sha256'] or any(sha(ROOT / n) != h for n, h in result['source_sha256'].items())):
        raise ValueError('final correspondence source/binary changed')
    requests, records = [], []
    def add(study, name, method, raw, packet):
        decode_exact(packet, raw)
        requests.append(packet)
        records.append({'study': study, 'input': name, 'method': method, 'raw_bytes': len(raw), 'packed_bytes': len(packet),
                        'raw_sha256': hashlib.sha256(raw).hexdigest(), 'packed_sha256': hashlib.sha256(packet).hexdigest()})
    cost = json.loads((ROOT / 'scripts/reports/search-cost.json').read_text())
    for record in cost['exact_rows']:
        add('S7', str(record['id']), 'exact', bytes.fromhex(record['raw_hex']), bytes.fromhex(record['native']['packed_hex']))
    mixed = json.loads((ROOT / 'scripts/reports/search-mixed.json').read_text())
    for record in mixed['witnesses']:
        add('S8', str(record['input_id']), record['method'], bytes.fromhex(record['raw_hex']), bytes.fromhex(record['packed_hex']))
    expected = {(r['input'], r['method']): r['packed_sha256'] for r in result['rows']} if result else {}
    temporary = directory / 'correspondence.deflate' if result else None
    for case in result['corpus']['cases'] if result else []:
        if case['scope'] != 'tiny' and case['family'] != 'real':
            continue
        path = directory / 'corpus' / case['path']
        raw = path.read_bytes()
        for name, method in result['finalists']['methods'].items():
            subprocess.check_output([str(ROOT / result['binary_path']), '--memory', str(path), str(temporary), method['worker']])
            packet = temporary.read_bytes()
            if sha(temporary) != expected[case['path'], name]:
                raise ValueError('correspondence packet differs from timed witness')
            add('S9', case['path'], name, raw, packet)
    print('Lean and Rust decoder packets', len(records), flush=True)
    lean = run_oracle([str(LEAN)], requests)
    rust = run_oracle([str(RUST), '--oracle'], requests)
    for record, model, native in zip(records, lean, rust):
        for party, decoded in (('Lean', model), ('Rust CLI', native)):
            if not decoded.ok or len(decoded.data) != record['raw_bytes'] or hashlib.sha256(decoded.data).hexdigest() != record['raw_sha256']:
                raise ValueError(f'{party} new-packet disagreement: {record}')
        record['lean_decoded_sha256'] = hashlib.sha256(model.data).hexdigest()
        record['rust_decoded_sha256'] = hashlib.sha256(native.data).hexdigest()
    if result is None:
        print('published model/native packet checks passed', len(records), flush=True)
        return
    report = {'packets': len(records), 'records': records, 'lean_binary_sha256': sha(LEAN), 'rust_cli_binary_sha256': sha(RUST),
              'final_binary_sha256': result['binary_sha256'], 'lean_toolchain': (ROOT / 'lean-toolchain').read_text().strip(),
              'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'spec').rglob('*.lean'))},
              'checker_sha256': sha(pathlib.Path(__file__)), 'scope': 'finite new S7/S8 witnesses and all S9 fresh real/tiny packets; no Rust refinement or performance proof'}
    (ROOT / 'scripts/reports/search-final-correspondence.json').write_text(json.dumps(report, indent=2) + '\n')
    print('all model/native packet checks passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--campaign', type=pathlib.Path)
    group.add_argument('--published-only', action='store_true')
    args = parser.parse_args()
    run(args.campaign.resolve() if args.campaign else None)
