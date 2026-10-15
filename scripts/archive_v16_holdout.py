#!/usr/bin/env python3
"""Archive the v16 holdout evaluation into one compact, checkable receipt.

Inputs live under target/library-v16 (arm64 runs) and target/library-v16/x86
(reports copied back from raps-ci). Timing samples are stored grouped per packet and method; the
packets and corpus bodies are not stored (they are re-creatable from the
pinned manifest). --check re-runs the preregistered analysis on the archived
rows and verifies it matches the stored verdicts.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import library_holdout_analyze as analysis  # noqa: E402

OUT = ROOT / "scripts/reports/library-decode-v16-holdout.json.gz"
BASE = ROOT / "target/library-v16"
RUNS = {"arm64-reuse": BASE / "arm64-reuse/report.json", "arm64-fresh": BASE / "arm64-fresh/report.json",
        "x86-reuse": BASE / "x86/x86-reuse/report.json", "x86-fresh": BASE / "x86/x86-fresh/report.json"}
CHECKS = {"arm64": BASE / "arm64-checks/checks.json", "x86": BASE / "x86/x86-checks/checks.json"}
METHODS = ["candidate", "baseline", "zlib-ng", "libdeflate"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(report):
    """Group samples as samples[packet][method] = [decode_ns by session, first_decode_ns by session].

    decode_iterations/batch_calls were validated by library_bench.py at run time
    and are not needed by the analysis; they are not archived. decode_ns is a
    per-call mean rounded to whole ns (at most 0.03% on the
    smallest packets), far below timer noise.
    """
    rows = report["rows"]
    meta = {k: v for k, v in report.items() if k not in ("rows", "corpus_manifest", "summary")}
    meta["native_build"] = [{"codec": w["codec"], "direction": w["direction"], "binary_sha256": w["binary_sha256"],
                             "reference_libraries": w["reference"]["libraries"]}
                            for w in report["native_build"]["workers"]]
    packets = sorted({(r["case"], r["frame"], r["encoder"], r["raw_bytes"], r["packed_bytes"], r["packet_sha256"])
                      for r in rows})
    index = {p[:3]: i for i, p in enumerate(packets)}
    sessions = report["sessions"]
    samples = [[[[None] * sessions, [None] * sessions] for _ in METHODS] for _ in packets]
    for r in rows:
        cell = samples[index[(r["case"], r["frame"], r["encoder"])]][METHODS.index(r["method"])]
        cell[0][r["session"]] = round(r["decode_ns"])
        cell[1][r["session"]] = r.get("first_decode_ns")
    return {"meta": meta, "summary": report["summary"], "methods": METHODS,
            "packet_columns": ["case", "frame", "encoder", "raw_bytes", "packed_bytes", "packet_sha256"],
            "packets": [list(p) for p in packets], "samples": samples}


def expand(run):
    rows = []
    for packet, methods in zip(run["packets"], run["samples"]):
        base = dict(zip(run["packet_columns"], packet))
        for method, (decode, first) in zip(run["methods"], methods):
            for session, (d, f) in enumerate(zip(decode, first)):
                rows.append({**base, "method": method, "session": session, "decode_ns": d, "first_decode_ns": f})
    return {"rows": rows}


def build():
    manifest_path = BASE / "corpus/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    bands = {c["name"]: c["scope"] for c in manifest["cases"]}
    runs, verdicts = {}, {}
    for name, path in RUNS.items():
        report = json.loads(path.read_text())
        runs[name] = compact(report)
        results, first_call = analysis.analyze(expand(runs[name]), bands)
        verdicts[name] = {"results": results, "first_call_median_ns": first_call}
    checks = {}
    for arch, path in CHECKS.items():
        data = json.loads(path.read_text())
        checks[arch] = {k: data[k] for k in ("host", "machine", "seed", "flips", "corpus_manifest_sha256",
                                             "decoders", "malformed_rows", "zlib_accepts", "disagreements", "memory")}
        checks[arch]["mutation_summary"] = {
            "zlib_accept": sum(r["zlib"] == "accept" for r in data["malformed"]),
            "zlib_reject": sum(r["zlib"] == "reject" for r in data["malformed"])}
    extra = {}
    for name in ["prereg.sha256", "bin.sha256", "arm64.log", "x86/bin.sha256", "x86/bin.sizes", "x86/load.txt",
                 "x86/toolchain.txt", "x86/reference-libs.txt", "sizes.txt"]:
        path = BASE / name
        if path.exists():
            extra[name] = path.read_text()[-20000:]
    receipt = {"schema_version": 1, "study": "library-decode-v16-holdout",
               "preregistration": {"path": "docs/library-decode-v16-preregistration.md",
                                   "sha256": sha(ROOT / "docs/library-decode-v16-preregistration.md")},
               "corpus_manifest": manifest, "corpus_manifest_sha256": sha(manifest_path),
               "scripts": {p: sha(ROOT / p) for p in ["scripts/library_bench.py", "scripts/library_holdout_corpus.py",
                                                      "scripts/library_holdout_checks.py",
                                                      "scripts/library_holdout_analyze.py",
                                                      "scripts/library_decode_worker.c"]},
               "runs": runs, "verdicts": verdicts, "checks": checks, "host_records": extra}
    OUT.write_bytes(gzip.compress(json.dumps(receipt, separators=(",", ":")).encode(), mtime=0))
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size} bytes")


def check():
    receipt = json.loads(gzip.decompress(OUT.read_bytes()))
    if receipt["preregistration"]["sha256"] != sha(ROOT / "docs/library-decode-v16-preregistration.md"):
        raise SystemExit("preregistration changed since archiving")
    bands = {c["name"]: c["scope"] for c in receipt["corpus_manifest"]["cases"]}
    for name, run in receipt["runs"].items():
        results, first_call = analysis.analyze(expand(run), bands)
        stored = receipt["verdicts"][name]
        if json.loads(json.dumps(results)) != stored["results"] or \
                json.loads(json.dumps(first_call)) != stored["first_call_median_ns"]:
            raise SystemExit(f"{name}: re-analysis differs from archived verdicts")
    for arch, data in receipt["checks"].items():
        if data["disagreements"]:
            raise SystemExit(f"{arch}: malformed-input disagreements present")
    print("v16 holdout receipt: analysis reproduces; no malformed disagreements")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    (check if parser.parse_args().check else build)()
