#!/usr/bin/env python3
"""Publish exact-bit witnesses and bounded-parser results, including rejections."""
import argparse
import gzip
import json
import math
import pathlib

from search_campaign import confidence
from search_corpus import ROOT
from search_cpu import aggregate
from search_poc import sha


def publish(directory):
    result = json.loads((directory / 'result.json').read_text())
    for name, digest in result['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('measured parser source changed')
    if sha(directory / 'finalists.json') != result['finalists_sha256']:
        raise ValueError('parser finalist freeze changed')
    if json.loads((directory / 'finalists.json').read_text()) != result['finalists']:
        raise ValueError('reported finalists differ from frozen selection')
    if json.loads((directory / 'exact-oracle.json').read_text()) != result['exact_rows']:
        raise ValueError('reported oracle differs from retained witness')
    if sha(directory / 'corpus/manifest.json') != result['manifest_sha256']:
        raise ValueError('parser corpus manifest changed')
    for case in result['corpus']['cases']:
        path = directory / 'corpus' / case['path']
        if path.stat().st_size != case['bytes'] or sha(path) != case['sha256']:
            raise ValueError('parser corpus payload changed')
    for build in result['builds'].values():
        if sha(ROOT / build['binary_path']) != build['binary_sha256']:
            raise ValueError('compiled geometry binary changed')
    output = ROOT / 'scripts/reports'
    ledger = output / 'search-cost-measurements.jsonl.gz'
    count = 0
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped:
        for event in result['training'] + result['validation']:
            cases = [c for c in result['corpus']['cases'] if c['partition'] == event['partition']]
            if len(event['rows']) != len(cases) or {r['input'] for r in event['rows']} != {pathlib.PurePosixPath(c['path']).name for c in cases}:
                raise ValueError('incomplete parser matrix')
            if aggregate(event['rows']) != event['aggregate']:
                raise ValueError('parser aggregate differs from paired rounds')
            for row in event['rows']:
                case = next(c for c in cases if pathlib.PurePosixPath(c['path']).name == row['input'])
                rounds = result['protocol']['training_rounds' if event['partition'] == 'train' else 'validation_rounds']
                if row['raw_bytes'] != case['bytes'] or any(len(row[f]) != rounds or not all(math.isfinite(v) and v > 0 for v in row[f]) for f in ('samples_ns', 'baseline_samples_ns')):
                    raise ValueError('invalid parser sizes or paired rounds')
                for suffix, field, size in (('.deflate', 'packed_sha256', 'packed_bytes'), ('.baseline.deflate', 'baseline_packed_sha256', 'baseline_bytes')):
                    path = directory / event['partition'] / event['id'] / 'streams' / (row['input'] + suffix)
                    if sha(path) != row[field] or path.stat().st_size != row[size]:
                        raise ValueError('parser stream witness changed')
                zipped.write((json.dumps({**row, 'partition': event['partition'], 'config_id': event['id']}, separators=(',', ':'), allow_nan=False) + '\n').encode())
                count += 1
    if count != result['verified_rows']:
        raise ValueError('wrong parser evidence count')
    def compact(event):
        record = {k: v for k, v in event.items() if k != 'rows'}
        cases = [c for c in result['corpus']['cases'] if c['partition'] == event['partition']]
        for scope, selected in [('real-regression-chunks', [c for c in cases if c['family'] == 'real']),
                                ('synthetic-regression', [c for c in cases if c['family'] != 'real' and c['dataset'] == 'previous']),
                                ('synthetic-extended', [c for c in cases if c['dataset'] == 'extended'])]:
            if not selected:
                continue
            names = {pathlib.PurePosixPath(c['path']).name for c in selected}
            rows = [r for r in event['rows'] if r['input'] in names]
            record[scope] = {'aggregate': aggregate(rows), 'confidence': confidence(rows, selected, 2000, result['protocol']['seed']),
                             'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in rows)}
        return record
    report = {k: v for k, v in result.items() if k not in ('training', 'validation')}
    report.update(training=[compact(e) for e in result['training']], validation=[compact(e) for e in result['validation']],
                  raw_rows=count, raw_ledger=str(ledger.relative_to(ROOT)), raw_ledger_sha256=sha(ledger),
                  analysis_source_sha256=sha(pathlib.Path(__file__)),
                  limitations=['exact oracle optimality is one fixed-code block only; no dynamic/global heuristic optimality claim',
                               'DP is optimal over its bounded candidate graph and raw-chunk boundaries under fixed costs; auto emission can change those costs',
                               'geometry applies to the isolated research parser, not production Matcher',
                               'real validation uses chunks of previously visible files; fresh final cases remain reserved',
                               'table capacity is not peak RSS; no longer warm/cold, decode/tiny or binary-size gate yet',
                               'near-4GiB check is an arithmetic model of absolute links, not a native 4GiB encode or a Rust refinement proof'])
    (output / 'search-cost.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/encoded-cost-report.md').write_text(render(report))
    print(json.dumps({'rows': count, 'ledger_bytes': ledger.stat().st_size}))


def label(event):
    config = event['config']
    if 'layout' not in config:
        return config['method']
    layout = config['layout']
    return f"{config['method']} / hash {layout['hash_bits']} / history {layout['window_bytes']}"


def render(report):
    exact_rows = report['exact_rows']
    bit_wins = sum(r['oracle']['fixed_bits'] < r['greedy']['fixed_bits'] for r in exact_rows)
    byte_wins = sum(r['oracle']['packed_bytes'] < r['greedy']['packed_bytes'] for r in exact_rows)
    lines = ['# S1 geometry and S7: encoded-cost parsing', '',
             f"The short exact oracle improves fixed-code bits in {bit_wins}/{len(exact_rows)} constructed cases",
             f"and whole bytes in {byte_wins}/{len(exact_rows)}. Every native exact bit count matches",
             'the independent Python oracle, and every output passes deflate-core,',
             'miniz_oxide and exact-consumption zlib. An additional exhaustive forward',
             'parse enumeration covers all binary inputs through eight bytes.', '',
             'The oracle solves a position DAG containing every legal literal/match',
             'edge, with literal 8/9-bit costs, length/distance codes and extra bits,',
             'three header bits, seven EOB bits and final byte padding.',
             '[RFC 1951](https://www.rfc-editor.org/rfc/rfc1951.html)',
             'This optimality is for one fixed-code block. It does not cover dynamic',
             'Huffman costs, other candidate graphs or block splitting.', '',
             '## Bounded native prototype and geometry', '',
             'The native prototype inserts all positions into a three-byte hash chain,',
             'scans at most 4/16/64 candidates and parses raw chunks of 512/4096/16384',
             'bytes. Greedy chooses the longest match; fixed-cost DP considers all legal',
             'prefix lengths and their cheapest available distance. Nearer matches with',
             'equal or longer prefixes dominate older fixed-cost candidates. Tests check',
             'DP is no worse than greedy on the same graph and exercise repeated ring',
             'wraps. Every emitted match is compared to input bytes with distances',
             'bounded by the compiled history, never exceeding 32768.', '',
             'Eight hash/history layouts are compiled into isolated source/compiler/flags',
             'keyed builds. Hash widths 12–18 and histories 1–32 KiB are validated;',
             'the experiment samples eight layouts. Default, small and large table',
             'capacities are 512 KiB, 40 KiB and 2.25 MiB on this 64-bit machine.',
             'These are research-parser tables, not changes to production Matcher.',
             'Exact mode has no ignored external probe/layout fields; production preset',
             'candidate identities mask inactive geometry fields.', '',
             'Fixed mode emits a single fixed block. Auto mode reuses the checked',
             'fixed/dynamic emitter with 16384-token splits and a whole-input stored',
             'fallback. It does not implement S8 mixed stored blocks. Dynamic codes',
             'are rebuilt from selected tokens, so fixed-cost DP can worsen actual',
             'dynamic output. No optimality is claimed for auto emission.', '',
             'Sixty training and 44 validation cases combine previous mixed workloads',
             'with new cost-sensitive matches, three hash-collision generators, change',
             'points/drift, sampling traps and paired transforms. Real files are capped',
             'at 256 KiB with source ranges retained. Old validation is regression;',
             'new synthetic regimes are separately identified. Fourteen canonical',
             'methods/layouts are frozen before validation; roles use training only.',
             'All predeclared methods/layouts remain validation sentinels. The 14 prior',
             'synthetic and 18 extension tests remain unencoded; S5 final cases also',
             'remain reserved. Five training/seven validation paired rounds use 5 ms',
             'minimum batches. Timings include matching, parsing, allocation and emission.', '',
             '## Native validation', '',
             '| Method / geometry | Speed vs paired Balanced | Packed-size change | Maximum file-size ratio |',
             '| --- | ---: | ---: | ---: |']
    for event in report['validation']:
        a = event['aggregate']
        lines.append(f"| {label(event)} | {a['speed_vs_paired_balanced']:.3f}× | {100*(a['size_vs_balanced']-1):+.3f}% | {event['max_file_size_vs_balanced']:.3f}× |")
    lines += ['', 'Scope aggregates and source/family/paired-round confidence intervals',
              'are retained in the JSON. Table rows combine the mixed cases; the real,',
              'old synthetic and extended synthetic scopes must also be inspected.', '',
              '## Decision and verification boundary', '',
              'The exact counterexamples validate the parsing hypothesis under fixed',
              'codes. The bounded prototype does not belong in production Best: its',
              'encoder cost is high and its worst-file growth exceeds the predeclared',
              '20% guard. Training-selected speed/compromise stay Balanced and size',
              'stays Best. Retain the negative prototype and geometry findings.', '',
              'Existing Lean proofs cover the model’s checked finder and fixed/dynamic',
              'emission policies. They are not a refinement proof of this Rust parser',
              'or a theorem about encoded-size optimality. No Lean model or production',
              'core source changes. Three-decoder/byte-count/enumeration gates provide',
              'finite cross-implementation evidence. The 4GiB-boundary test shifts an',
              'absolute-link arithmetic model by 2^32 with small rings; it allocates',
              'no 4GiB input and does not establish native 32-bit portability.', '',
              '[Full evidence](../scripts/reports/search-cost.json) retains exact raw inputs,',
              'native packets/tokens, frozen roles, geometry/build provenance, case',
              'construction witnesses and raw observations in the',
              f"[gzip ledger](../scripts/reports/search-cost-measurements.jsonl.gz) ({report['raw_rows']} rows).", '',
              '```sh', 'make research-cost-check',
              'python3 scripts/search_extended_corpus.py --out target/search/EXTENSIONS',
              'python3 scripts/search_cost_campaign.py --extensions target/search/EXTENSIONS --out target/search/cost/RUN',
              'python3 scripts/search_cost_report.py --campaign target/search/cost/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    publish(parser.parse_args().campaign.resolve())
