#!/usr/bin/env python3
"""Validate and archive the v12 raw hot-loop screen (negative result) once."""
import gzip
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "target/library-v12"
OUTPUT = ROOT / "scripts/reports/library-decode-v12-hot-loop.json.gz"
BASELINE = "e12ba57441147b839a9092a7cab3864b52400de16bb4606e98b78d54dc3cdd86"
SCREENS = {
    "aa": "baseline binary timed against itself (noise calibration)",
    "a": "out-of-line copy for match bytes beyond forty",
    "b": "single disjoint 40-byte copy when distance >= 40",
}
CANDIDATES = {
    "a": "eddfacc787610d9b0eceef32d8e40ca17253d691d9bc14c6f9a05e0b93da98cf",
    "b": "a60c117eebcd765fb6e47cea1ef54ac1b3cf1ebcd5b1335f3fdfecbde7eab93c",
    "c": "36ef29e6222284f6b3c9609975c78bc7345ef38aa634bf8293853157ce513646",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(path):
    lines = Path(path).read_text().splitlines()[2:]
    return [re.sub(r"0x[0-9a-f]+|<.*|;.*", "", line.split(":", 1)[-1]).strip() for line in lines]


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
        }
    return out


assert sha(RUN / "baseline-library_decode_reuse") == BASELINE
for name, digest in CANDIDATES.items():
    assert sha(RUN / f"cand-{name}-library_decode_reuse") == digest, name
screens = {}
for name, scope in SCREENS.items():
    report = json.loads((RUN / f"screen-{name}/report.json").read_text())
    # Timed binaries are bound by hash. The report's source_sha256 records the
    # working tree at measurement time, which for "aa" was candidate A.
    for method in report["methods"].values():
        assert sha(method["binary"]) == method["sha256"], method["binary"]
    assert report["methods"]["baseline"]["sha256"] == BASELINE
    screens[name] = {"scope": scope, "summary": paired(report), "report": report}
asm = {n: normalized(RUN / f) for n, f in
       (("baseline", "baseline-decode_tokens.asm"), ("c", "cand-c.asm"))}
assert asm["baseline"] == asm["c"]

receipt = {
    "schema_version": 1,
    "study": "raw DEFLATE hot-loop screen v12 (all candidates rejected)",
    "controller_sha256": sha(Path(__file__)),
    "baseline_sha256": BASELINE,
    "candidate_sha256": CANDIDATES,
    "patches": {n: (RUN / f"patches/candidate-{n}.diff").read_text() for n in CANDIDATES},
    "candidate_c_decode_tokens_normalized_identical": True,
    "decode_tokens_instructions": len(asm["baseline"]),
    "screens": screens,
}
with OUTPUT.open("xb") as stream:
    stream.write(
        gzip.compress((json.dumps(receipt, separators=(",", ":")) + "\n").encode(), mtime=0)
    )
for name, screen in screens.items():
    raw = screen["summary"]["raw"]
    print(
        f"{name}: pooled {raw['pooled_candidate_speedup']:+.2%}, "
        f"median paired {raw['median_paired_speedup']:+.2%}"
    )
