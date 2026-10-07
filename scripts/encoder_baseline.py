#!/usr/bin/env python3
"""Preserve the completed S9 native worker before encoder implementation changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "14f15e63e1a8955c5cfebf869ce065f29dd950fc"
DEFAULT_OUT = ROOT / "target/encoder-performance/baseline"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(out):
    meta = json.loads((out / "baseline.json").read_text())
    if meta["commit"] != BASELINE:
        raise ValueError("unexpected baseline commit")
    for name, digest in meta["artifacts"].items():
        if sha(out / name) != digest:
            raise ValueError("baseline artifact changed: " + name)
    return meta


def freeze(out):
    if out.exists():
        raise ValueError("baseline directory exists; use --check")
    report_path = ROOT / "scripts/reports/search-final.json"
    report = json.loads(report_path.read_text())
    binary = ROOT / report["binary_path"]
    if sha(binary) != report["binary_sha256"]:
        raise ValueError("S9 worker hash mismatch")
    compiler = subprocess.check_output(["rustc", "--version"], text=True).strip()
    if compiler != report["rustc"]:
        raise ValueError("baseline compiler changed")
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT, text=True).splitlines()
    names = [n for n in tracked if n.startswith("crates/deflate-core/") and n.endswith(".rs")]
    names += ["Cargo.toml", "Cargo.lock", "crates/deflate-core/Cargo.toml", "lean-toolchain"]
    current = {}
    for name in names:
        expected = subprocess.check_output(["git", "show", BASELINE + ":" + name], cwd=ROOT)
        digest = hashlib.sha256(expected).hexdigest()
        if sha(ROOT / name) != digest:
            raise ValueError("freeze before changing baseline source: " + name)
        current[name] = digest
    for name, digest in report["source_sha256"].items():
        if name.startswith("crates/deflate-core/") or name in ("Cargo.toml", "Cargo.lock", "lean-toolchain"):
            if sha(ROOT / name) != digest:
                raise ValueError("current production source differs from measured S9: " + name)
    out.mkdir(parents=True)
    shutil.copy2(binary, out / "final_bench")
    (out / "source.tar.gz").write_bytes(subprocess.check_output(["git", "archive", "--format=tar.gz", BASELINE], cwd=ROOT))
    methods = report["finalists"]["methods"]
    for name, method in methods.items():
        if "policy" in method:
            file = out / (name + ".policy")
            file.write_text(method["policy"])
            if sha(file) != method["policy_sha256"]:
                raise ValueError("S9 policy payload mismatch")
            method["worker"] = "policy@" + str(file.resolve())
    (out / "methods.json").write_text(json.dumps(methods, indent=2) + "\n")
    overrides = {k: v for k, v in os.environ.items() if k.startswith("CARGO_PROFILE_") or k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")}
    if overrides != report["build_overrides"]:
        raise ValueError("build overrides differ from measured baseline")
    artifacts = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    meta = {"schema_version": 1, "commit": BASELINE, "rustc": compiler,
            "build_overrides": overrides, "reference": "miniz_oxide 0.8.9 raw levels 1/6/9",
            "s9_report_sha256": sha(report_path), "source_sha256": current,
            "artifacts": artifacts, "note": "sealed original worker; no new holdout input encoded"}
    (out / "baseline.json").write_text(json.dumps(meta, indent=2) + "\n")
    return check(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check(args.out) if args.check else freeze(args.out)
    print(json.dumps({"commit": result["commit"], "artifacts": len(result["artifacts"]),
                      "baseline": str(args.out / "baseline.json")}))
