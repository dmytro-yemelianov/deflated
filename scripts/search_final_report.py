#!/usr/bin/env python3
"""Export S9 session confidence, direct references, guard failures and decisions."""
import argparse
import collections
import gzip
import json
import pathlib
import statistics

from search_corpus import ROOT, validate
from search_final_stats import direct, summary
from search_poc import sha


def gates(name, result, metrics, direct_metrics):
    protocol = result['protocol']
    bound = protocol['guardrails']
    role = 'size' if name.endswith('size') else 'compromise' if name.endswith('compromise') else 'speed'
    fresh, tiny = metrics['fresh'], metrics['tiny']
    base = 'best' if role == 'size' else 'balanced'
    against = direct_metrics[base]['fresh']
    tiny_against = direct_metrics[base]['tiny']
    checks = {'maximum_file_size': fresh['max_file_size_vs_balanced'] <= bound['maximum_file_size_vs_balanced']}
    if role == 'size':
        checks['aggregate_size'] = fresh['size_vs_balanced'] <= bound['size_maximum_aggregate_size_vs_balanced']
        checks['warm_speed'] = against['session_bootstrap_95pct']['warm_speed'][0] >= bound['size_minimum_speed_lower_95pct_vs_best']
        checks['cold_speed'] = against['session_bootstrap_95pct']['cold_speed'][0] >= bound['size_minimum_speed_lower_95pct_vs_best']
    else:
        checks['aggregate_size'] = fresh['size_vs_balanced'] <= bound[role + '_aggregate_size_vs_balanced']
        checks['warm_speed'] = fresh['session_bootstrap_95pct']['warm_speed'][0] >= bound['minimum_speed_lower_95pct_vs_balanced']
        checks['cold_speed'] = fresh['session_bootstrap_95pct']['cold_speed'][0] >= bound['minimum_speed_lower_95pct_vs_balanced']
    checks['warm_decode'] = against['session_bootstrap_95pct']['warm_decode_time'][1] <= bound['maximum_decode_time_vs_baseline']
    checks['cold_decode'] = against['session_bootstrap_95pct']['cold_decode_time'][1] <= bound['maximum_decode_time_vs_baseline']
    tiny_max = max(f['warm_encode_ns'] / f['warm_reference_encode_ns'] for f in tiny_against['per_file'].values())
    checks['tiny_latency'] = tiny_max <= bound['maximum_tiny_encode_time_vs_baseline']
    memory = collections.defaultdict(list)
    for row in result['rss']:
        memory[row['method'], row['case']['path']].append(row['peak_rss_bytes'])
    memory_increase = max(statistics.median(values) - statistics.median(memory[base, path]) for (method, path), values in memory.items() if method == name)
    checks['peak_rss'] = memory_increase <= bound['maximum_rss_increase_bytes']
    size_increase = result['size_builds'][name]['release']['total_bytes'] - result['size_builds'][base]['release']['total_bytes']
    checks['linked_release_size'] = size_increase <= bound['maximum_release_probe_increase_bytes']
    return {'role': role, 'baseline': base, 'checks': checks, 'all_measured_guards_pass': all(checks.values()),
            'maximum_tiny_warm_latency_ratio': tiny_max, 'maximum_median_process_rss_increase_bytes': memory_increase,
            'linked_release_probe_increase_bytes': size_increase,
            'decision': 'retain opt-in research profile; no default change or production integration claim' if all(checks.values()) else 'reject production promotion; retain measured tradeoff',
            'failed_guards': [key for key, value in checks.items() if not value]}


def publish(directory):
    result = json.loads((directory / 'result.json').read_text())
    model_path = ROOT / 'scripts/reports/search-final-correspondence.json'
    model = json.loads(model_path.read_text())
    if model['final_binary_sha256'] != result['binary_sha256']:
        raise ValueError('new-packet Lean checks belong to a different final binary')
    if any(sha(ROOT / n) != h for n, h in result['source_sha256'].items()) or sha(ROOT / result['binary_path']) != result['binary_sha256']:
        raise ValueError('final measured sources/binary changed')
    if sha(directory / 'finalists.json') != result['finalists_sha256'] or json.loads((directory / 'finalists.json').read_text()) != result['finalists']:
        raise ValueError('final frozen selection changed')
    if sha(directory / 'corpus/manifest.json') != result['manifest_sha256']:
        raise ValueError('final manifest changed')
    validate(directory / 'corpus', result['corpus'])
    for builds in result['size_builds'].values():
        for build in builds.values():
            if sha(ROOT / build['binary_path']) != build['binary_sha256'] or (ROOT / build['binary_path']).stat().st_size != build['binary_bytes']:
                raise ValueError('final linked-size probe changed')
    rows = [json.loads(line) for line in (directory / 'measurements.jsonl').read_text().splitlines()]
    if rows != result['rows'] or len(rows) != result['verified_rows']:
        raise ValueError('final raw observations changed')
    ledger = ROOT / 'scripts/reports/search-final-measurements.jsonl.gz'
    with ledger.open('wb') as stream, gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped:
        for row in rows:
            zipped.write((json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n').encode())
    cases = {c['path']: c for c in result['corpus']['cases']}
    scopes = {'fresh': {p for p, c in cases.items() if c['scope'] == 'fresh'},
              'fresh-real': {p for p, c in cases.items() if c['scope'] == 'fresh' and c['family'] == 'real'},
              'fresh-synthetic': {p for p, c in cases.items() if c['scope'] == 'fresh' and c['family'] != 'real'},
              'tiny': {p for p, c in cases.items() if c['scope'] == 'tiny'}}
    for family in sorted({c['family'] for c in cases.values() if c['scope'] == 'fresh' and c['family'] != 'real'}):
        scopes['family-' + family] = {p for p, c in cases.items() if c['scope'] == 'fresh' and c['family'] == family}
    grouped = {name: [r for r in rows if r['method'] == name] for name in result['finalists']['methods']}
    seed = result['protocol']['seed']
    metrics = {name: {scope: summary([r for r in group if r['input'] in paths], seed) for scope, paths in scopes.items()} for name, group in grouped.items()}
    references = {}
    for name in result['protocol']['roles'].values():
        references[name] = {ref: {scope: direct([r for r in grouped[name] if r['input'] in scopes[scope]], [r for r in grouped[ref] if r['input'] in scopes[scope]], seed)
                                 for scope in ('fresh', 'fresh-real', 'fresh-synthetic', 'tiny')} for ref in ('balanced', 'best', 'miniz1', 'miniz6', 'miniz9')}
    decisions = {name: gates(name, result, metrics[name], references[name]) for name in result['protocol']['roles'].values()}
    frontier = []
    for name, values in metrics.items():
        a = values['fresh']
        point = (a['summed_file_medians_ns']['encode_ns'], a['packed_bytes'])
        if not any(all(x <= y for x, y in zip((v['fresh']['summed_file_medians_ns']['encode_ns'], v['fresh']['packed_bytes']), point)) and
                   any(x < y for x, y in zip((v['fresh']['summed_file_medians_ns']['encode_ns'], v['fresh']['packed_bytes']), point)) for other, v in metrics.items() if other != name):
            frontier.append(name)
    report = {k: v for k, v in result.items() if k != 'rows'}
    report.update(metrics=metrics, direct_references=references, decisions=decisions, fresh_warm_speed_size_frontier=frontier,
                  raw_rows=len(rows), raw_ledger=str(ledger.relative_to(ROOT)), raw_ledger_sha256=sha(ledger), analysis_source_sha256=sha(pathlib.Path(__file__)),
                  statistics_source_sha256=sha(ROOT / 'scripts/search_final_stats.py'), promotion='no production defaults changed; see role-specific measured decisions',
                  aborted_attempt={'report': 'scripts/reports/search-final-aborted.json', 'sha256': sha(ROOT / 'scripts/reports/search-final-aborted.json'),
                                   'reason': 'file rotation cancelled method/pair rotation; discarded from final claims and fixed before this series; no candidates/thresholds changed'},
                  model_correspondence={'report': str(model_path.relative_to(ROOT)), 'sha256': sha(model_path), 'packets': model['packets'], 'lean_toolchain': model['lean_toolchain']},
                  limitations=['one Apple M5; Linux CI provides correctness only, no second-hardware speed claim',
                               'reserved regimes use public deterministic recipes; six Calgary files are the only fresh real sources',
                               'cold means fresh-process first calls with resident input, not cold OS/disk/code caches',
                               'confidence resamples ten complete sessions, not an independent population of input families',
                               'RSS is entire single-encode process on three representative inputs, not isolated encoder heap or all possible files',
                               'release/min probes retain shared runtime method parser; binary sizes are prototype accounting, not production integration',
                               'no superiority outside measured host, levels and cases; no global optimum or formally verified Rust claim'])
    profile = ROOT / 'scripts/reports/final-size.policy'
    profile.write_text(result['finalists']['methods']['policy-size']['policy'])
    if sha(profile) != result['finalists']['methods']['policy-size']['policy_sha256']:
        raise ValueError('exported size policy differs from frozen measured policy')
    report['retained_size_policy'] = {'path': str(profile.relative_to(ROOT)), 'sha256': sha(profile)}
    (ROOT / 'scripts/reports/search-final.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (ROOT / 'docs/final-tuning-report.md').write_text(render(report))
    print(json.dumps({'rows': len(rows), 'ledger_bytes': ledger.stat().st_size, 'decisions': decisions}))


def render(report):
    lines = ['# S9: frozen final tuning validation', '',
             f"Measured on {report['cpu']} ({report['machine']}), {report['rustc']}.",
             'The direct encoder reference is the locked dev-dependency miniz_oxide',
             '0.8.9 at raw DEFLATE levels 1/6/9. Every reference measurement is made',
             'inside this study; historical baseline figures are not substituted.',
             'Eleven methods were frozen before encoding 44 reserved cases (six fresh',
             'Calgary sources and 38 synthetic cases) and 19 tiny inputs. Ten complete',
             'sessions rotate files, methods and candidate/baseline order. Warm batches',
             'last at least 20 ms (2 ms for tiny inputs). Encoder allocation, matching,',
             'policy selection and emission are included; input I/O and oracle checks',
             'are excluded. Decoder timings use deflate-core for every encoder’s output.', '',
             'Cold observations are first calls in separate fresh processes with',
             'resident input and parsed policy. They include fresh encoder/decoder',
             'allocations, exclude startup and input I/O, and do not represent cold OS,',
             'disk or instruction caches. Every candidate/baseline packet agrees across',
             'sessions and warm/cold paths and passes three decoders. No final-test',
             'feedback changes the candidates, policies, budgets or thresholds.', '',
             'An earlier 3015-row attempt was stopped when file rotation was found',
             'to cancel method/pair rotation. Its source hashes and raw observations',
             'remain in the [aborted report](../scripts/reports/search-final-aborted.json).',
             'Those observations are excluded from final claims. The corrected',
             'schedule covers ten distinct method positions and five candidate-first',
             'and five baseline-first pairs for every fixed input/method.', '',
             '## Fresh aggregate', '',
             '| Method | Median warm speed vs paired Balanced | Session mean [95% CI] | Median cold speed | Packed-size change | Worst file ratio |',
             '| --- | ---: | --- | ---: | ---: | ---: |']
    for name, metrics in report['metrics'].items():
        a = metrics['fresh']
        ci = a['session_bootstrap_95pct']['warm_speed']
        lines.append(f"| {name} | {a['warm_speed_vs_balanced']:.3f}× | {a['session_paired_estimates']['warm_speed']:.3f}× [{ci[0]:.3f}, {ci[1]:.3f}] | {a['cold_speed_vs_balanced']:.3f}× | {100*(a['size_vs_balanced']-1):+.3f}% | {a['max_file_size_vs_balanced']:.3f}× |")
    lines += ['', 'Throughput ratios use summed per-file medians. Session bootstrap',
              'confidence bounds apply to pooled paired session-mean ratios, whose',
              'point estimates are separately reported. Guard decisions use those',
              'predeclared session bounds; these two estimators are kept distinct.', '',
              'Session confidence describes repeat noise on these fixed cases. It',
              'does not establish generalization to another population or machine.',
              'The JSON separates real/synthetic/family scopes and per-file medians.', '',
              '## Direct native references on the same fresh cases', '',
              '| Frozen role candidate / miniz level | Warm speed vs reference | Packed-size change from reference |',
              '| --- | ---: | ---: |']
    for role, reference in (('speed', 'miniz1'), ('compromise', 'miniz6'), ('size', 'miniz9'), ('policy-speed', 'miniz1'), ('policy-size', 'miniz9')):
        name = report['protocol']['roles'][role]
        a = report['direct_references'][name][reference]['fresh']
        lines.append(f"| {name} / {reference} | {a['warm_speed_vs_reference']:.3f}× | {100*(a['size_vs_reference']-1):+.3f}% |")
    lines += ['', 'Direct comparisons pair the same input/session and preserve the',
              'actual native reference encoder timings.', '',
              '## Decode, tiny-input, memory and linked-size gates', '',
              'Three separate `/usr/bin/time` single-encode repetitions per method cover',
              'the largest reserved input, largest fresh real file and largest previous',
              'full real file. Darwin RSS is measured in bytes; Linux parsing converts',
              'KiB to bytes. The prior full file is memory-only regression evidence.',
              'Peak RSS includes the process, resident input, tables, temporaries and',
              'output; it is not reported as encoder-only heap.', '',
              'All 22 release/min linked probes were built before timing and their',
              'packets match the main worker on a private verification input. Sizes',
              'include external policy payloads and retain the shared runtime parser.',
              'The min profile is measured for size only, not advertised for speed.', '',
              '| Candidate | Failed measured guards | Maximum tiny warm latency ratio | Maximum RSS increase | Release probe increase |',
              '| --- | --- | ---: | ---: | ---: |']
    for name, decision in report['decisions'].items():
        lines.append(f"| {name} | {', '.join(decision['failed_guards']) or 'none'} | {decision['maximum_tiny_warm_latency_ratio']:.3f}× | {decision['maximum_median_process_rss_increase_bytes']} B | {decision['linked_release_probe_increase_bytes']} B |")
    lines += ['', 'Thresholds were frozen in the protocol before final encoding. Size',
              'roles use Best for speed/decode/tiny/RSS/linked-size comparisons; speed',
              'and compromise use Balanced. Both warm/cold session confidence bounds',
              'must pass encoder and decoder limits. The tiny guard checks the worst',
              'per-input warm median, so large files cannot conceal tiny regressions.', '',
              '## Decision', '']
    for name, decision in report['decisions'].items():
        lines.append(f"- **{name}:** {decision['decision']}.")
    lines += ['', 'Production defaults remain unchanged. Existing Lean model theorems',
              'cover checked finder/token and fixed/dynamic/whole-stored policies,',
              'not heuristic quality, runtime speed or a Rust refinement. S7 and S8',
              'remain rejected isolated prototypes with documented model boundaries.', '',
              f"The [new-packet correspondence ledger](../scripts/reports/search-final-correspondence.json) also checks {report['model_correspondence']['packets']} packets through",
              'the actual Lean and Rust CLI decoders: every S7 exact and S8 mixed',
              'witness plus every S9 fresh real/tiny output. Decoded lengths/hashes',
              'match the input and timed packet hashes. This is finite model evidence.', '',
              'The measured [size policy](../scripts/reports/final-size.policy) passes',
              'the predeclared guards and improves on Best on this fixed mixed set.',
              'It is still dominated by miniz6 in the aggregate speed/size comparison;',
              'passing internal guards does not establish superiority over references.',
              'Use it only as an opt-in research profile:', '',
              '```sh', 'cargo build --locked --release -p deflate-core --example final_bench --features research-tuning',
              'target/release/examples/final_bench --memory INPUT.raw OUTPUT.deflate policy@scripts/reports/final-size.policy', '```', '',
              f"[Report](../scripts/reports/search-final.json) and [raw ledger](../scripts/reports/search-final-measurements.jsonl.gz) retain {report['raw_rows']} paired rows,",
              'all session observations, corpus membership, source/build/policy hashes,',
              'RSS tool output, linked probe counts, reference comparisons and failures.', '',
              '```sh', 'make research-final-check',
              'python3 scripts/search_final_campaign.py --out target/search/final/RUN',
              'python3 scripts/search_final_correspondence.py --campaign target/search/final/RUN',
              'python3 scripts/search_final_report.py --campaign target/search/final/RUN', '```', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=pathlib.Path, required=True)
    publish(parser.parse_args().campaign.resolve())
