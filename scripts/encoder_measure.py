#!/usr/bin/env python3
"""Paired non-holdout measurements with the sealed original native worker."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, validate, write_json
from search_poc import decode_exact

OUTLIERS = (
    "test/fresh-1-feature_sampling_trap-5-0.raw",
    "test/fresh-0-new-template_edits-1021.raw",
    "test/fresh-1-collision_trigram-5-0.raw",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs(corpus, partition="train", outliers=True):
    if partition not in ("train", "validation"):
        raise ValueError("new final-test inputs are inaccessible to pilot/profile runs")
    meta = json.loads((corpus / "manifest.json").read_text())
    validate(corpus, meta)
    selected = [{**c, "raw_path": str((corpus / c["path"]).resolve()), "scope": "new-real-" + partition}
                for c in meta["cases"] if c["partition"] == partition]
    if outliers:
        old = json.loads((ROOT / "scripts/reports/search-final.json").read_text())
        for path in OUTLIERS:
            case = next(c for c in old["corpus"]["cases"] if c["path"] == path)
            raw_path = ROOT / "target/search/final-s9-rotated/corpus" / path
            if sha(raw_path) != case["sha256"]:
                raise ValueError("old outlier changed")
            selected.append({"path": path, "raw_path": str(raw_path), "scope": "old-regression",
                             "family": case["family"], "class": "synthetic", "source_group": "s9-" + case["family"],
                             "bytes": case["bytes"], "sha256": case["sha256"], "partition": "regression"})
    return selected


def summary(rows, cases, methods):
    by_scope = {}
    for scope in sorted({c["scope"] for c in cases}):
        selected = [c for c in cases if c["scope"] == scope]
        table = {}
        for name in methods:
            encode, baseline, packed, base_packed, ratios = [], [], [], [], []
            for case in selected:
                found = [r for r in rows if r["method"] == name and r["input"] == case["raw_path"]]
                encode.append(statistics.median(r["encode_ns"] for r in found))
                baseline.append(statistics.median(r["baseline_encode_ns"] for r in found))
                sizes = {(r["packed_bytes"], r["baseline_bytes"], r["packed_sha256"], r["baseline_packed_sha256"]) for r in found}
                if len(sizes) != 1:
                    raise ValueError("nondeterministic measured output")
                size, base, _, _ = sizes.pop()
                packed.append(size)
                base_packed.append(base)
                ratios.append(size / base)
            table[name] = {"warm_speed_vs_paired_balanced": sum(baseline) / sum(encode),
                           "packed_size_change_pct": 100 * (sum(packed) / sum(base_packed) - 1),
                           "worst_file_size_ratio": max(ratios), "raw_bytes": sum(c["bytes"] for c in selected),
                           "encode_median_ns_sum": sum(encode), "packed_bytes": sum(packed)}
        by_scope[scope] = table
    return by_scope


def run(out, corpus, baseline, partition, rounds, minimum):
    if rounds < 1 or minimum < 1:
        raise ValueError("positive rounds and minimum required")
    frozen_baseline = check_baseline(baseline)
    cases = inputs(corpus, partition)
    methods = json.loads((baseline / "methods.json").read_text())
    binary = baseline / "final_bench"
    names = list(methods)
    out.mkdir(parents=True, exist_ok=False)
    frozen = {"baseline_metadata_sha256": sha(baseline / "baseline.json"),
              "methods_sha256": sha(baseline / "methods.json"), "corpus_sha256": sha(corpus / "manifest.json"),
              "binary_sha256": sha(binary)}
    write_json(out / "protocol.json", {"rounds": rounds, "minimum_ms": minimum,
               "partition": partition, "cases": cases, "methods": methods, "frozen": frozen,
               "purpose": "warm baseline pilot; no final-test encoding or promotion decision"})
    rows, current = [], None
    started = time.perf_counter()
    try:
        with (out / "measurements.jsonl").open("w") as log:
            for session in range(rounds):
                print("baseline session", session, flush=True)
                offset = session % len(cases)
                for original_index in list(range(offset, len(cases))) + list(range(offset)):
                    case = cases[original_index]
                    raw = Path(case["raw_path"]).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != case["sha256"]:
                        raise ValueError("raw input changed")
                    rotation = (session + original_index) % len(names)
                    for method_order, name in enumerate(names[rotation:] + names[:rotation]):
                        pair_order = (session + original_index + names.index(name)) % 2
                        current = {"session": session, "input": case["raw_path"], "method": name}
                        row = json.loads(subprocess.check_output([str(binary), "warm", case["raw_path"],
                            str(out / "current-streams"), str(minimum), methods[name]["worker"], str(pair_order)], text=True, timeout=120))
                        for side, size_field in (("candidate", "packed_bytes"), ("baseline", "baseline_bytes")):
                            packet = (out / "current-streams" / (side + ".deflate")).read_bytes()
                            decode_exact(packet, raw)
                            if len(packet) != row[size_field] or row["raw_bytes"] != len(raw):
                                raise ValueError("native packet size differs")
                            row["packed_sha256" if side == "candidate" else "baseline_packed_sha256"] = hashlib.sha256(packet).hexdigest()
                        for field in ("encode_ns", "baseline_encode_ns", "decode_ns", "baseline_decode_ns"):
                            if not math.isfinite(row[field]) or row[field] <= 0:
                                raise ValueError("invalid timing")
                        row.update(current, scope=case["scope"], family=case["family"], source_group=case["source_group"],
                                   method_order=method_order, pair_order=pair_order)
                        rows.append(row)
                        log.write(json.dumps(row, allow_nan=False) + "\n")
                        log.flush()
        if check_baseline(baseline) != frozen_baseline or sha(corpus / "manifest.json") != frozen["corpus_sha256"]:
            raise ValueError("measurement contract changed")
        inputs(corpus, partition)
        result = {"protocol": json.loads((out / "protocol.json").read_text()), "rows": len(rows),
                  "metrics": summary(rows, cases, methods), "elapsed_seconds": time.perf_counter() - started,
                  "platform": platform.platform(), "python": platform.python_version(),
                  "native_rustc": frozen_baseline["rustc"], "raw_ledger_sha256": sha(out / "measurements.jsonl"),
                  "limitations": ["five-session warm pilot by default; no cold/RSS/final promotion evidence", "fixed measured cases on this machine"]}
        write_json(out / "result.json", result)
        print(json.dumps({"rows": len(rows), "metrics": result["metrics"]}, indent=2))
    except BaseException as error:
        write_json(out / "failed.json", {"current": current, "rows": len(rows), "error": str(error), "frozen": frozen})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=CORPUS_OUT)
    parser.add_argument("--baseline", type=Path, default=BASELINE_OUT)
    parser.add_argument("--partition", choices=("train", "validation"), default="train")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--minimum-ms", type=int, default=10)
    args = parser.parse_args()
    run(args.out, args.corpus, args.baseline, args.partition, args.rounds, args.minimum_ms)
