#!/usr/bin/env python3
"""Validate and archive the v15 small-input latency study once (arm64).

Rows are stored compactly (one tuple per timed sample) to keep the receipt
small; packet/raw hashes are kept per packet, binaries by hash.
"""
import gzip
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "target/library-v15"
OUTPUT = ROOT / "scripts/reports/library-decode-v15-small-latency.json.gz"
BASE_COMMIT = "1c0e00c"
RUNS = {
    "base-reuse": "baseline: accel (candidate) and core (baseline), reused state/output",
    "base-fresh": "baseline: accel (candidate) and core (baseline), fresh calls",
    "aa-reuse": "baseline core timed against itself (noise calibration)",
    "screen-a": "candidate A: 8-byte peek_bits fast path, core reuse",
    "screen-ab": "candidates A+B: plus wide-counter prepare (B rejected), core reuse",
    "screen-ac": "candidates A+C: plus fused code-length decode, core reuse",
    "screen-c": "candidate C alone, core reuse",
    "ac-final-core-reuse": "A+C vs baseline, core, reused (superseded: A rejected)",
    "ac-final-core-fresh": "A+C vs baseline, core, fresh (superseded)",
    "ac-final-accel-reuse": "A+C vs baseline, deflate-accel, reused (superseded)",
    "ac-final-accel-fresh": "A+C vs baseline, deflate-accel, fresh (superseded)",
    "ac-guard-real": "A+C large-input guard: v11 real corpus, per-call timer",
    "ac-guard-real-2": "A+C large-input guard repeat",
    "iso-go-a": "go-only isolation: A alone vs baseline, per-call timer, 7 sessions",
    "iso-go-c": "go-only isolation: C alone vs baseline, per-call timer, 7 sessions",
    "final-core-reuse": "kept set (C) vs baseline, core, reused",
    "final-core-fresh": "kept set (C) vs baseline, core, fresh",
    "final-accel-reuse": "kept set (C) vs baseline, deflate-accel, reused",
    "final-accel-fresh": "kept set (C) vs baseline, deflate-accel, fresh",
    "guard-real": "kept set (C) large-input regression guard: v11 real corpus, per-call timer",
}
# Full rows only where verdicts rest on them; screens keep summaries.
ROWS = {"base-reuse", "base-fresh", "aa-reuse", "final-core-reuse", "final-core-fresh",
        "final-accel-reuse", "final-accel-fresh", "guard-real", "iso-go-a"}
PER_CALL = {"ac-guard-real", "ac-guard-real-2", "iso-go-a", "iso-go-c", "guard-real"}
PATCHES = ["cand-a", "cand-b", "cand-c"]
FIELDS = ["case", "frame", "encoder", "session", "method", "decode_ns", "batch_calls"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paired(rows, a="candidate", b="baseline"):
    """Median over matched samples of b/a - 1 (positive: candidate faster)."""
    ns = {(r["case"], r["frame"], r["encoder"], r["session"], r["method"]): r["decode_ns"]
          for r in rows}
    out = {}
    for frame in ("raw", "gzip"):
        ratios = {}
        for (case, f, encoder, session, method), value in ns.items():
            if f == frame and method == a:
                ratios.setdefault(case, []).append(ns[(case, f, encoder, session, b)] / value)
        every = [x for values in ratios.values() for x in values]
        out[frame] = {
            "median_paired_speedup": statistics.median(every) - 1,
            "per_case_median_speedup": {c: statistics.median(v) - 1 for c, v in ratios.items()},
        }
    return out


def per_case_ns(rows):
    """Median over sessions, then over the three encoders."""
    acc = {}
    for r in rows:
        acc.setdefault((r["case"], r["frame"], r["method"], r["encoder"]), []).append(r["decode_ns"])
    by = {}
    for (case, frame, method, _), values in acc.items():
        by.setdefault(f"{case}/{frame}/{method}", []).append(statistics.median(values))
    return {key: statistics.median(values) for key, values in by.items()}


PROFILE = json.loads((RUN / "profiles/attrib.json").read_text())
runs = {}
for name, scope in RUNS.items():
    report = json.loads((RUN / name / "report.json").read_text())
    for method in report["methods"].values():
        binary = Path(method["binary"])
        if name.startswith("ac-") and binary.name.startswith("final-"):
            # The rejected A+C binaries were renamed before the C-only rerun.
            binary = binary.with_name("ac-" + binary.name)
        assert sha(binary) == method["sha256"], binary
    rows = report["rows"]
    packets = {f"{r['case']}.{r['encoder']}.{r['frame']}": r["packet_sha256"] for r in rows}
    runs[name] = {
        "scope": scope,
        "timer": report.get("timer", "per-call clock read"),
        "context": report["context"],
        "methods": {m: {"sha256": v["sha256"], "bytes": v["bytes"]}
                    for m, v in report["methods"].items()},
        "source_sha256": report["source_sha256"],
        "revision": report["revision"],
        "sessions": report["sessions"],
        "minimum_ns": report["minimum_ns"],
        "rejection_contracts": report["rejection_contracts"],
        "packet_sha256": packets,
        "summary": report["summary"],
        "paired": paired(rows),
        "per_case_ns": per_case_ns(rows),
        "row_fields": FIELDS,
    }
    if name in ROWS:
        # decode_ns rounded to 0.1 ns; verdicts above use the unrounded rows.
        runs[name]["rows"] = [[round(r[f], 1) if f == "decode_ns" else r.get(f)
                               for f in FIELDS] for r in rows]
    if name not in PER_CALL:
        assert runs[name]["timer"].startswith("batched"), name
for name in ("aa-reuse", "screen-a", "screen-ab", "screen-ac", "screen-c",
             "ac-final-core-reuse", "final-core-reuse"):
    assert runs[name]["methods"]["baseline"]["sha256"] == \
        runs["base-reuse"]["methods"]["baseline"]["sha256"], name

receipt = {
    "schema_version": 1,
    "study": "v15 small-input latency: batched timer, header-path candidates",
    "controller_sha256": sha(Path(__file__)),
    "base_commit": BASE_COMMIT,
    "host": json.loads((RUN / "base-reuse/report.json").read_text())["host"],
    "rustc": json.loads((RUN / "base-reuse/report.json").read_text())["rustc"],
    "native_build": json.loads((RUN / "workers/build.json").read_text()),
    "small_corpus_manifest": json.loads((RUN / "small-corpus.json").read_text()),
    "load": {name: (RUN / name).read_text() for name in
             ("load-baseline.txt", "ac-load-final.txt", "load-final.txt", "screen-a.load",
              "screen-ab.load", "screen-ac.load", "screen-c.load")},
    "kept": ["cand-c"],
    "rejected": {
        "cand-a": "8-byte peek_bits fast path: go gzip +2.8-3.3% in three large-input runs "
                  "(A alone isolates it) and tiny raw +4%; C alone keeps most small gains",
        "cand-b": "wide-counter prepare: serial store/load chain on zero runs; "
                  "go-100 and vega-100 ~+20% slower",
    },
    "patches": {name: (RUN / f"{name}.patch").read_text() for name in PATCHES},
    "final_source_diff": subprocess.check_output(
        ["git", "-C", ROOT, "diff", BASE_COMMIT, "--", "crates/deflate-core/src"], text=True),
    "profile_attribution": {
        "binary_sha256": PROFILE["binary_sha256"],
        "note": PROFILE["note"],
        "profiles": [{k: v for k, v in prof.items() if k != "pcs"} | {
            "top_pcs": prof["pcs"][:20]} for prof in PROFILE["profiles"]],
    },
    "runs": runs,
    "limitations": "arm64 development host under variable load; batched timer differs from "
                   "earlier per-call receipts, so earlier tiny ns/call are not comparable; "
                   "diagnostic prefixes of four pinned real inputs, not holdout.",
}
OUTPUT.write_bytes(gzip.compress(json.dumps(receipt, sort_keys=True).encode(), mtime=0))
print(OUTPUT, OUTPUT.stat().st_size)
