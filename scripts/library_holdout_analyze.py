#!/usr/bin/env python3
"""Apply the v16 preregistered decision rule to library_bench.py receipts.

Per packet (case x frame x encoder-level), the paired ratio against a
reference is median_ns(reference) / median_ns(ours) over sessions; >1 means
ours is faster. Per (band, frame, implementation, reference) the statistic is
the median of packet ratios. Its 95% interval is a cluster bootstrap that
resamples SOURCE BODIES (a tiny prefix and the concatenation map to their own
clusters as listed below), 10,000 resamples, seed 16.

A workload qualifies when, for BOTH references, the median >= 1.0 and the
bootstrap lower bound >= 1.0, and no case's geometric-mean ratio is < 0.90.
"""
import argparse
import gzip
import json
import math
from pathlib import Path
import random
import statistics

RESAMPLES = 10_000
SEED = 16
REFERENCES = ["zlib-ng", "libdeflate"]
OURS = {"candidate": "core", "baseline": "accel"}


def cluster(case):
    return case.split("-prefix")[0]


def load(path):
    blob = path.read_bytes()
    return json.loads(gzip.decompress(blob) if path.suffix == ".gz" else blob)


def packet_medians(rows):
    table = {}
    for row in rows:
        key = (row["case"], row["frame"], row["encoder"])
        table.setdefault(key, {}).setdefault(row["method"], []).append(row["decode_ns"])
    return {key: {m: statistics.median(v) for m, v in methods.items()} for key, methods in table.items()}


def bootstrap(ratios_by_cluster, rng):
    clusters = list(ratios_by_cluster)
    values = []
    for _ in range(RESAMPLES):
        sample = [r for c in (rng.choice(clusters) for _ in clusters) for r in ratios_by_cluster[c]]
        values.append(statistics.median(sample))
    values.sort()
    return values[int(0.025 * RESAMPLES)], values[int(0.975 * RESAMPLES) - 1]


def analyze(receipt, bands):
    medians = packet_medians(receipt["rows"])
    raw_bytes = {(r["case"], r["frame"], r["encoder"]): r["raw_bytes"] for r in receipt["rows"]}
    rng = random.Random(SEED)
    results = []
    for band in ["tiny", "small", "medium", "large"]:
        for frame in ["raw", "gzip"]:
            keys = sorted(k for k in medians if bands[k[0]] == band and k[1] == frame)
            if not keys:
                continue
            throughput = {m: sum(raw_bytes[k] for k in keys) * 1000 / sum(medians[k][m] for k in keys)
                          for m in medians[keys[0]]}
            for ours_method, ours in OURS.items():
                entry = {"band": band, "frame": frame, "implementation": ours, "packets": len(keys),
                         "cases": len({k[0] for k in keys}), "MB_per_s": throughput, "vs": {}}
                qualifies = True
                for reference in REFERENCES:
                    ratio = {k: medians[k][reference] / medians[k][ours_method] for k in keys}
                    by_cluster = {}
                    for k, r in ratio.items():
                        by_cluster.setdefault(cluster(k[0]), []).append(r)
                    low, high = bootstrap(by_cluster, rng)
                    per_case = {}
                    for k, r in ratio.items():
                        per_case.setdefault(k[0], []).append(math.log(r))
                    case_geo = {c: math.exp(sum(v) / len(v)) for c, v in per_case.items()}
                    worst = min(case_geo, key=case_geo.get)
                    median = statistics.median(ratio.values())
                    ok = median >= 1.0 and low >= 1.0 and case_geo[worst] >= 0.90
                    qualifies &= ok
                    entry["vs"][reference] = {"median_ratio": median, "ci95": [low, high],
                                              "worst_case": worst, "worst_case_geomean": case_geo[worst],
                                              "cases_below_0_90": sorted(c for c, g in case_geo.items() if g < 0.90),
                                              "passes": ok}
                entry["qualifies"] = qualifies
                results.append(entry)
    first_call = {}
    for row in receipt["rows"]:
        if "first_decode_ns" in row:
            band = bands[row["case"]]
            first_call.setdefault((band, row["frame"], row["method"]), []).append(row["first_decode_ns"])
    return results, {f"{b}/{f}/{m}": statistics.median(v) for (b, f, m), v in sorted(first_call.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("receipts", type=Path, nargs="+")
    args = parser.parse_args()
    bands = {c["name"]: c["scope"] for c in json.loads(args.corpus.read_text())["cases"]}
    for path in args.receipts:
        receipt = load(path)
        results, first_call = analyze(receipt, bands)
        print(json.dumps({"receipt": str(path), "context": receipt["rows"][0].get("context"),
                          "results": results, "first_call_median_ns": first_call}))


if __name__ == "__main__":
    main()
