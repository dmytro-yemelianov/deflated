#!/usr/bin/env python3
"""Validate and archive the v14 decode-candidate screens once (arm64 + x86-64)."""
import gzip
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "target/library-v14"
X86 = RUN / "x86/container/target/library-v14"
OUTPUT = ROOT / "scripts/reports/library-decode-v14-decode-candidates.json.gz"
BASE_COMMIT = "5805003"
BASELINE = "e12ba57441147b839a9092a7cab3864b52400de16bb4606e98b78d54dc3cdd86"
ARM64 = {
    "aa": "baseline core timed against itself (noise calibration)",
    "cand1-11": "candidate 1: 11-bit literal/length root with subtables",
    "cand1-10": "candidate 1 variant: 10-bit root with subtables",
    "cand2": "candidate 2: branch-free fast-loop refill",
    "cand3-core": "candidate 3 core change: forced inlining, single bulk call site",
    "cand3-accel": "candidate 3: deflate-accel with x86-64 BMI2 dispatch (plain path on arm64)",
    "combo12": "candidates 1+2, core",
    "combo123-core": "candidates 1+2+3, core",
    "combo123-accel": "candidates 1+2+3, deflate-accel",
    "final-core": "kept set built from the working tree, core, 5 sessions",
    "final-accel": "kept set built from the working tree, deflate-accel, 5 sessions",
}
X86_RUNS = {
    "aa": "baseline core timed against itself (noise calibration)",
    "cand1": "candidate 1 (11-bit root), core",
    "cand2": "candidate 2, core",
    "cand3-core": "candidate 3 core change",
    "cand3-accel": "candidate 3, deflate-accel with BMI2 dispatch",
    "combo12": "candidates 1+2, core",
    "combo123-accel": "candidates 1+2+3, deflate-accel",
    "final-core": "candidates 1+2+3, core, 5 sessions",
    "final-accel": "candidates 1+2+3, deflate-accel, 5 sessions",
}
PATCHES = [
    "cand1-subtable11", "cand1-subtable10", "cand2-refill", "cand3-bmi2",
    "combo-1-2", "combo-1-2-3",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paired(report):
    ns = {
        (r["case"], r["frame"], r["encoder"], r["session"], r["method"]): r["decode_ns"]
        for r in report["rows"]
    }
    out = {}
    for frame in ("raw", "gzip"):
        ratios = {}
        for (case, f, encoder, session, method), value in ns.items():
            if f == frame and method == "candidate":
                base = ns[(case, f, encoder, session, "baseline")]
                ratios.setdefault(case, []).append(base / value)
        every = [x for values in ratios.values() for x in values]
        totals, sizes = {}, {}
        for r in report["rows"]:
            if r["frame"] == frame:
                totals[r["method"]] = totals.get(r["method"], 0) + r["decode_ns"]
                sizes[r["method"]] = sizes.get(r["method"], 0) + r["raw_bytes"]
        out[frame] = {
            "pooled_mb_s": {m: sizes[m] / totals[m] * 1e3 for m in sorted(totals)},
            "pooled_candidate_speedup": totals["baseline"] / totals["candidate"] - 1,
            "median_paired_speedup": statistics.median(every) - 1,
            "geomean_paired_speedup": math.exp(sum(map(math.log, every)) / len(every)) - 1,
            "per_case_median_speedup": {
                case: statistics.median(values) - 1 for case, values in sorted(ratios.items())
            },
            "per_case_min_speedup": {case: min(values) - 1 for case, values in sorted(ratios.items())},
        }
    return out


assert sha(RUN / "baseline-library_decode_reuse") == BASELINE
arm64 = {}
for name, scope in ARM64.items():
    report = json.loads((RUN / f"screen-{name}/report.json").read_text())
    # Timed binaries are bound by hash. A screen's source_sha256 is the working
    # tree at measurement time: HEAD for every screen except final-*.
    for method in report["methods"].values():
        assert sha(method["binary"]) == method["sha256"], method["binary"]
    arm64[name] = {"scope": scope, "summary": paired(report), "report": report}
for name in ("aa", "cand1-11", "cand1-10", "cand2", "cand3-core", "combo12", "combo123-core",
             "final-core"):
    assert arm64[name]["report"]["methods"]["baseline"]["sha256"] == BASELINE, name

x86_binaries = {}
for line in (X86 / "binaries.sha256").read_text().splitlines():
    digest, path = line.split()
    x86_binaries[Path(path).name] = digest
x86 = {}
for name, scope in X86_RUNS.items():
    report = json.loads((X86 / f"measure-{name}/report.json").read_text())
    for method in ("candidate", "baseline"):
        assert report["methods"][method]["sha256"] in x86_binaries.values(), (name, method)
    x86[name] = {"scope": scope, "summary": paired(report), "report": report}
counters = json.loads((X86 / "counters/counters.json").read_text())

receipt = {
    "schema_version": 1,
    "study": "v14 decode candidates: subtable root, branch-free refill, BMI2 dispatch",
    "controller_sha256": sha(Path(__file__)),
    "base_commit": BASE_COMMIT,
    "arm64_baseline_sha256": BASELINE,
    "kept": ["cand1-subtable11", "cand2-refill", "cand3-bmi2"],
    "rejected": {"cand1-subtable10": "10-bit root: go raw median -1.9% on arm64; 11-bit kept"},
    "final_source_diff": subprocess.check_output(
        ["git", "-C", ROOT, "diff", BASE_COMMIT, "--", "crates"], text=True
    ),
    "patches": {name: (RUN / f"{name}.patch").read_text() for name in PATCHES},
    "x86_binaries_sha256": x86_binaries,
    "x86_toolchain": (X86 / "toolchain.txt").read_text(),
    "x86_bmi2_instruction_counts": (X86 / "bmi2-count.txt").read_text(),
    "x86_cpu_reports_bmi2": (X86 / "cpu-bmi2.txt").read_text().strip() == "bmi2",
    "arm64": arm64,
    "x86": x86,
    "x86_counters": counters,
}
with OUTPUT.open("xb") as stream:
    stream.write(
        gzip.compress((json.dumps(receipt, separators=(",", ":")) + "\n").encode(), mtime=0)
    )
for arch, runs in (("arm64", arm64), ("x86", x86)):
    for name, run in runs.items():
        raw, gz = run["summary"]["raw"], run["summary"]["gzip"]
        print(
            f"{arch:5} {name:15} raw median {raw['median_paired_speedup']:+.2%} "
            f"gzip median {gz['median_paired_speedup']:+.2%}"
        )
