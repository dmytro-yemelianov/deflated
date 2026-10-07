#!/usr/bin/env python3
"""Export S8 including matched no-stored controls and the Lean scope decision."""
import argparse
import gzip
import json
import pathlib

from search_campaign import confidence
from search_corpus import ROOT, validate
from search_cpu import aggregate
from search_poc import sha


def publish(directory):
    result = json.loads((directory / 'result.json').read_text())
    corpus = ROOT / result['corpus_path']
    validate(corpus, result['corpus'])
    if sha(corpus / 'manifest.json') != result['manifest_sha256'] or any(sha(ROOT / n) != h for n, h in result['source_sha256'].items()):
        raise ValueError('mixed-emission measured sources/corpus changed')
    if sha(ROOT / result['build']['binary_path']) != result['build']['binary_sha256']:
        raise ValueError('mixed-emission binary changed')
    if sha(directory / 'finalists.json') != result['finalists_sha256'] or json.loads((directory / 'finalists.json').read_text()) != result['finalists']:
        raise ValueError('mixed-emission freeze changed')
    if json.loads((directory / 'witnesses.json').read_text()) != result['witnesses']:
        raise ValueError('mixed-emission witnesses changed')
    ledger = ROOT / 'scripts/reports/search-mixed-measurements.jsonl.gz'
    count = 0
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped:
        for event in result['training'] + result['validation']:
            cases = [c for c in result['corpus']['cases'] if c['partition'] == event['partition']]
            if len(event['rows']) != len(cases) or {r['input'] for r in event['rows']} != {pathlib.PurePosixPath(c['path']).name for c in cases} or aggregate(event['rows']) != event['aggregate']:
                raise ValueError('mixed-emission matrix differs')
            for row in event['rows']:
                for suffix, field in (('.deflate', 'packed_sha256'), ('.baseline.deflate', 'baseline_packed_sha256')):
                    if sha(directory / event['partition'] / event['id'] / 'streams' / (row['input'] + suffix)) != row[field]:
                        raise ValueError('mixed-emission stream witness changed')
                zipped.write((json.dumps({**row, 'partition': event['partition'], 'config_id': event['id']}, separators=(',', ':'), allow_nan=False) + '\n').encode())
                count += 1
    def compact(event):
        record = {k: v for k, v in event.items() if k != 'rows'}
        cases = [c for c in result['corpus']['cases'] if c['partition'] == event['partition']]
        for scope, selected in [('real-regression-chunks', [c for c in cases if c['family'] == 'real']),
                                ('synthetic-regression', [c for c in cases if c['family'] != 'real' and c['dataset'] == 'previous']),
                                ('synthetic-extended', [c for c in cases if c['dataset'] == 'extended'])]:
            names = {pathlib.PurePosixPath(c['path']).name for c in selected}
            rows = [r for r in event['rows'] if r['input'] in names]
            record[scope] = {'aggregate': aggregate(rows), 'confidence': confidence(rows, selected, 2000, result['protocol']['seed']),
                             'max_file_size_vs_balanced': max(r['packed_bytes'] / r['baseline_bytes'] for r in rows)}
        return record
    report = {k: v for k, v in result.items() if k not in ('training', 'validation')}
    if count != report['verified_rows']:
        raise ValueError('mixed-emission evidence count differs')
    report.update(training=[compact(e) for e in result['training']], validation=[compact(e) for e in result['validation']],
                  raw_rows=count, raw_ledger=str(ledger.relative_to(ROOT)), raw_ledger_sha256=sha(ledger),
                  analysis_source_sha256=sha(pathlib.Path(__file__)),
                  decision='reject production replacement; training roles remain Balanced/Best',
                  proof_boundary='existing emitSplitBlocksGo uses emitBlock fixed/dynamic, compressSplit has only whole-input stored fallback; mixed stored append and eight-offset DP are outside that theorem',
                  limitations=['fixed token partition and checked per-block lengths only, no global splitting/Huffman optimality',
                               'real validation is previously visible capped-file regression; reserved tests unencoded',
                               'one Apple M5; finite three-decoder, enumeration and byte-count evidence, no Rust refinement proof',
                               'timing includes eager token/length/cost/planning/evidence allocations; no peak-RSS or final gate in this spike'])
    (ROOT / 'scripts/reports/search-mixed.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/mixed-block-report.md').write_text(render(report))
    print(json.dumps({'rows': count, 'ledger_bytes': ledger.stat().st_size}))


def render(report):
    methods = {e['config']['method']: e for e in report['validation']}
    lines = ['# S8: alignment-aware stored/fixed/dynamic blocks', '',
             'The prototype finds the minimum final padded bit count for an existing',
             'token partition and its checked per-block Huffman lengths. Its eight',
             'states track the current bit offset. Fixed/dynamic transitions include',
             'headers and EOB; stored transitions include the three header bits,',
             'alignment, LEN/NLEN, payload and additional 65535-byte segments.',
             'Final byte padding participates in the recurrence. Blocks share one',
             'writer; exactly the last segment is final, and matches may reference',
             'bytes previously emitted by stored blocks.', '',
             'This is not a globally optimal splitter or Huffman-code optimizer.',
             'The outside whole-input stored option applies to both mixed and',
             'compressed-only controls without allocating a discarded stream.', '',
             '## Native experiment', '',
             'Three presets × three token limits (1024/4096/16384) × mixed versus',
             'compressed-only emission plus three unchanged presets give 21 methods.',
             'Five training/seven validation paired rounds (5 ms minimum batches)',
             'cover the S7 60/44 mixed cases. All methods are frozen validation',
             'sentinels; role selection uses training only. Real validation is',
             'previously visible 256 KiB chunks, and 32 reserved cases stay unencoded.',
             'Timing includes token collection, frequency/code construction, planning,',
             'emission and the prototype’s evidence allocations.', '',
             '| Native validation method | Speed vs paired Balanced | Packed-size change | Maximum file ratio |',
             '| --- | ---: | ---: | ---: |']
    for method, event in methods.items():
        a = event['aggregate']
        lines.append(f"| {method} | {a['speed_vs_paired_balanced']:.3f}× | {100*(a['size_vs_balanced']-1):+.3f}% | {event['max_file_size_vs_balanced']:.3f}× |")
    lines += ['', '## Matched mixed versus compressed-only byte counts', '',
              '| Preset / token limit | Mixed-size change from matched no-stored control |',
              '| --- | ---: |']
    for level in report['protocol']['levels']:
        for limit in report['protocol']['token_limits']:
            mixed = methods[f'mixed:{level}:{limit}']['aggregate']['packed_bytes']
            control = methods[f'compressed:{level}:{limit}']['aggregate']['packed_bytes']
            lines.append(f'| {level} / {limit} | {100*(mixed/control-1):+.4f}% |')
    lines += ['', 'Mixed emission cannot increase size against its matched control with',
              'the same token partition. It still loses the training-selected overall',
              'tradeoff to unchanged presets: speed/compromise select Balanced; size',
              'selects Best. Retain the mechanism and negative production decision.', '',
              '## Correctness and model scope', '',
              'Every measured candidate and paired baseline passes deflate-core,',
              'miniz_oxide and exact-consumption zlib. Native tests compare the DP',
              'against every type sequence for up to seven blocks at all eight offsets.',
              'Actual stored append packets cover every offset and payload lengths',
              '0/65535/65536/131071; mixed packets exercise backreferences across',
              'block histories, and emitted bits equal the predicted costs.', '',
              '`spec/Deflate/EncodeSplit.lean:emitSplitBlocksGo` calls `emitBlock`',
              'for fixed/dynamic blocks. `compressSplit` and `Compress.compress`',
              'choose stored only for the entire input. Those encoder theorems do',
              'not cover this mixed stored append operation or selection recurrence.',
              'Production promotion would need an append/alignment model and decoder',
              'loop invariant for arbitrary prior output. No production or Lean source',
              'changes are made; format tests are finite evidence, not a Rust proof.', '',
              f"[Report](../scripts/reports/search-mixed.json) and [raw ledger](../scripts/reports/search-mixed-measurements.jsonl.gz) retain {report['raw_rows']} paired rows,",
              'native packet witnesses, source/build hashes, frozen roles and scopes.', '',
              '```sh', 'make research-mixed-check',
              'python3 scripts/search_mixed_campaign.py --out target/search/mixed/RUN',
              'python3 scripts/search_mixed_report.py --campaign target/search/mixed/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    publish(parser.parse_args().campaign.resolve())
