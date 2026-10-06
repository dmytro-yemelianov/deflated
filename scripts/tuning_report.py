#!/usr/bin/env python3
"""Measure the frozen corpus split and render its speed/size tradeoffs.

python3 scripts/tuning_corpus.py
python3 scripts/tuning_report.py --baseline-ref 04eae11 --record
python3 scripts/tuning_report.py --check
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import platform
import re
import subprocess
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "scripts/reports/tuning.json"
DOC = ROOT / "docs/tuning-report.md"
SOURCES = ["crates/deflate-core/src/matcher.rs", "crates/deflate-core/src/compress.rs",
           "crates/deflate-core/src/matcher_flat.rs",
           "crates/deflate-core/src/lib.rs",
           "crates/deflate-core/examples/tune.rs", "Cargo.toml", "Cargo.lock"]


def aggregate(rows, prefix="deflate_core"):
    raw = sum(r["raw_bytes"] for r in rows)
    size = sum(r[prefix + "_bytes"] for r in rows)
    ns = sum(r[prefix + "_ns"] for r in rows)
    return {"raw_bytes": raw, "compressed_bytes": size, "mb_s": raw / ns * 1e3}


def tables(report):
    out = {}
    for partition, cases in report["datasets"].items():
        base = aggregate(cases["baseline"])
        lines = ["| Preset | MB/s | Speed vs previous | Size vs previous | Speed vs reference | Size vs reference | Wins both |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for level, ref in [("fast", "miniz_l1"), ("balanced", "miniz_l6"), ("best", "miniz_l9")]:
            rows = cases[level]
            ours = aggregate(rows)
            theirs = aggregate(rows, ref)
            wins = sum(r["deflate_core_ns"] < r[ref + "_ns"] and r["deflate_core_bytes"] <= r[ref + "_bytes"] for r in rows)
            lines.append(f"| {level} (vs {ref.replace('miniz_l', 'level ')}) | {ours['mb_s']:.1f} | "
                         f"{ours['mb_s'] / base['mb_s']:.2f}× | "
                         f"{100 * (ours['compressed_bytes'] / base['compressed_bytes'] - 1):+.2f}% | "
                         f"{ours['mb_s'] / theirs['mb_s']:.2f}× | "
                         f"{100 * (ours['compressed_bytes'] / theirs['compressed_bytes'] - 1):+.2f}% | "
                         f"{wins}/{len(rows)} |")
        out[partition] = "\n".join(lines)
    return out


def render(report, check=False):
    original = DOC.read_text()
    doc = original
    for name, body in tables(report).items():
        pattern = rf"(<!-- tuning:{name} -->\n).*?(\n<!-- /tuning:{name} -->)"
        doc, n = re.subn(pattern, lambda m: m[1] + body + m[2], doc, flags=re.S)
        if n != 1:
            raise SystemExit(f"missing tuning:{name} marker")
    if check:
        if original != doc:
            raise SystemExit("tuning tables differ from committed measurements")
        for partition, cases in report["datasets"].items():
            expected = {r["input"]: r["bytes"] for r in report["corpus"] if r["partition"] == partition}
            for rows in cases.values():
                assert {r["input"]: r["raw_bytes"] for r in rows} == expected
                for row in rows:
                    for prefix in ["deflate_core", "miniz_l1", "miniz_l6", "miniz_l9"]:
                        assert row[prefix + "_ns"] > 0
                        assert row[prefix + "_bytes"] > 0
        print("tuning tables and corpus membership agree")
    else:
        DOC.write_text(doc)


def baseline_binary(ref):
    resolved = subprocess.check_output(["git", "rev-parse", ref], text=True).strip()
    dest = ROOT / "target/tuning-baseline-source"
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(["git", "archive", resolved, "Cargo.toml", "Cargo.lock", "crates/deflate-core"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(dest, filter="data")
    cargo = dest / "Cargo.toml"
    cargo.write_text(cargo.read_text().replace('"crates/deflate-core", "crates/vdeflate"', '"crates/deflate-core"'))
    harness = (ROOT / "crates/deflate-core/examples/tune.rs").read_text()
    start = harness.index("    let level = match")
    end = harness.index("    let mut files:", start)
    harness = harness[:start] + harness[end:]
    harness = harness.replace("deflate_core::deflate_with_level(black_box(&raw), level)", "deflate_core::deflate(black_box(&raw))")
    (dest / "crates/deflate-core/examples/tune.rs").write_text(harness)
    target = ROOT / "target/tuning-baseline-target"
    subprocess.run(["cargo", "build", "--locked", "--release", "--manifest-path", str(cargo),
                    "-p", "deflate-core", "--example", "tune"],
                   env={**os.environ, "CARGO_TARGET_DIR": str(target)}, check=True)
    return target / "release/examples/tune", resolved


def main():
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="04eae11")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--min-ms", type=int, default=20)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        render(json.loads(REPORT.read_text()), check=True)
        return
    corpus_root = ROOT / "target/tuning-corpus"
    manifest = json.loads((corpus_root / "manifest.json").read_text())
    for item in manifest:
        path = corpus_root / item["partition"] / item["input"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], path
    baseline, ref = baseline_binary(args.baseline_ref)
    subprocess.run(["cargo", "build", "--locked", "--release", "-p", "deflate-core", "--example", "tune"], check=True)
    current = ROOT / "target/release/examples/tune"
    try:
        cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        cpu = platform.processor()
    report = {"baseline_commit": ref, "cpu": cpu,
              "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
              "platform": platform.platform(), "profile": "release",
              "build_overrides": {k: v for k, v in os.environ.items() if k.startswith("CARGO_PROFILE_RELEASE_") or k == "RUSTFLAGS"},
              "reference": "miniz_oxide 0.8.9 levels 1, 6, 9",
              "rounds": args.reps, "minimum_batch_ms": args.min_ms,
              "method": "median in-process batch time, rotating algorithm order; aggregate sums per-file median times; both decoders validate all streams before timing",
              "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
              "binary_sha256": {"baseline": hashlib.sha256(baseline.read_bytes()).hexdigest(), "candidate": hashlib.sha256(current.read_bytes()).hexdigest()},
              "presets": {"fast": {"chain": 4, "lazy": False, "insert": "start and last 16 positions after long matches"},
                          "balanced": {"chain": 64, "trigram_chain": 128, "flat_sample": "eight 512-byte regions, each byte count at most 64; retained matcher", "short_period_sample": "eight 512-byte regions with period at most 16; compact trigram index", "lazy": True, "insert": "all positions, batched uniform and checked periodic runs"},
                          "best": {"chain": 512, "lazy": True, "insert": "all positions", "split": "encoded bit cost at quarter boundaries"}},
              "corpus": manifest, "datasets": {}}
    for partition in ["train", "holdout", "stress"]:
        report["datasets"][partition] = {}
        for level in ["baseline", "fast", "balanced", "best"]:
            binary = baseline if level == "baseline" else current
            print(f"measuring {partition}: {level}", flush=True)
            result = subprocess.check_output([str(binary), str(corpus_root / partition), str(args.reps), str(args.min_ms)],
                                             env={**os.environ, "TUNE_LEVEL": level}, text=True)
            rows = json.loads(result)
            report["datasets"][partition][level] = rows
            print(aggregate(rows), flush=True)
            (corpus_root / f"final-{partition}-{level}.json").write_text(result)
    output = REPORT if args.record else ROOT / "target/reports/tuning.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    if args.record:
        render(report)
    else:
        for name, table in tables(report).items():
            print(name + "\n" + table)


if __name__ == "__main__":
    main()
