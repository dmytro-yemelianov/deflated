"""Session-paired final statistics, separately from per-file medians and RSS."""
import collections
import random
import statistics


def quantiles(values):
    ordered = sorted(values)
    return [ordered[int((len(ordered) - 1) * q)] for q in (0.025, 0.975)]


def summary(rows, seed=195119, resamples=4000):
    files = collections.defaultdict(list)
    sessions = collections.defaultdict(list)
    for row in rows:
        files[row['input']].append(row)
        sessions[row['session']].append(row)
    fields = ('encode_ns', 'baseline_encode_ns', 'decode_ns', 'baseline_decode_ns',
              'cold_encode_ns', 'cold_baseline_encode_ns', 'cold_decode_ns', 'cold_baseline_decode_ns')
    totals = {f: sum(statistics.median(r[f] for r in group) for group in files.values()) for f in fields}
    raw = sum(group[0]['raw_bytes'] for group in files.values())
    packed = sum(group[0]['packed_bytes'] for group in files.values())
    baseline = sum(group[0]['baseline_bytes'] for group in files.values())
    result = {'files': len(files), 'sessions': len(sessions), 'raw_bytes': raw, 'packed_bytes': packed,
              'baseline_bytes': baseline, 'size_vs_balanced': packed / baseline,
              'max_file_size_vs_balanced': max(g[0]['packed_bytes'] / g[0]['baseline_bytes'] for g in files.values()),
              'warm_mb_s': raw * 1000 / totals['encode_ns'],
              'warm_speed_vs_balanced': totals['baseline_encode_ns'] / totals['encode_ns'],
              'cold_speed_vs_balanced': totals['cold_baseline_encode_ns'] / totals['cold_encode_ns'],
              'warm_decode_time_vs_balanced': totals['decode_ns'] / totals['baseline_decode_ns'],
              'cold_decode_time_vs_balanced': totals['cold_decode_ns'] / totals['cold_baseline_decode_ns'],
              'summed_file_medians_ns': totals,
              'per_file': {name: {'raw_bytes': group[0]['raw_bytes'], 'size_vs_balanced': group[0]['packed_bytes'] / group[0]['baseline_bytes'],
                                 'warm_encode_ns': statistics.median(r['encode_ns'] for r in group),
                                 'warm_baseline_encode_ns': statistics.median(r['baseline_encode_ns'] for r in group)} for name, group in sorted(files.items())}}
    session_totals = [{f: sum(r[f] for r in group) for f in fields} for _, group in sorted(sessions.items())]
    pooled = {f: sum(s[f] for s in session_totals) for f in fields}
    # Bootstrap below estimates ratios of pooled session means. Keep those
    # estimates distinct from throughput based on summed per-file medians.
    result['session_paired_estimates'] = {
        'warm_speed': pooled['baseline_encode_ns'] / pooled['encode_ns'],
        'cold_speed': pooled['cold_baseline_encode_ns'] / pooled['cold_encode_ns'],
        'warm_decode_time': pooled['decode_ns'] / pooled['baseline_decode_ns'],
        'cold_decode_time': pooled['cold_decode_ns'] / pooled['cold_baseline_decode_ns'],
    }
    rng = random.Random(seed)
    samples = {name: [] for name in ('warm_speed', 'cold_speed', 'warm_decode_time', 'cold_decode_time')}
    for _ in range(resamples):
        chosen = [rng.choice(session_totals) for _ in session_totals]
        summed = {f: sum(s[f] for s in chosen) for f in fields}
        samples['warm_speed'].append(summed['baseline_encode_ns'] / summed['encode_ns'])
        samples['cold_speed'].append(summed['cold_baseline_encode_ns'] / summed['cold_encode_ns'])
        samples['warm_decode_time'].append(summed['decode_ns'] / summed['baseline_decode_ns'])
        samples['cold_decode_time'].append(summed['cold_decode_ns'] / summed['cold_baseline_decode_ns'])
    result['session_bootstrap_95pct'] = {name: quantiles(value) for name, value in samples.items()}
    return result


def direct(candidate, reference, seed=195119, resamples=4000):
    ref = {(r['session'], r['input']): r for r in reference}
    paired = []
    for row in candidate:
        other = ref[row['session'], row['input']]
        paired.append({**row, 'baseline_bytes': other['packed_bytes'], 'baseline_encode_ns': other['encode_ns'],
                       'baseline_decode_ns': other['decode_ns'], 'cold_baseline_encode_ns': other['cold_encode_ns'],
                       'cold_baseline_decode_ns': other['cold_decode_ns']})
    result = summary(paired, seed, resamples)
    for key in tuple(result):
        if key.endswith('_vs_balanced'):
            result[key.replace('_vs_balanced', '_vs_reference')] = result.pop(key)
    for values in result['per_file'].values():
        values['size_vs_reference'] = values.pop('size_vs_balanced')
        values['warm_reference_encode_ns'] = values.pop('warm_baseline_encode_ns')
    return result
