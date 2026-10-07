#!/usr/bin/env python3
"""Build and isolate G0 Rust workers, guarding the immutable b7 core source.

This seals build inputs/binaries, not the complete reference measurement lock.
The same workers can be rebuilt in a fresh output directory for reproduction.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "b7d5e0fc79f4f72d2ba772312ec9a22497699ed5"
BINS = ["core_worker", "miniz_worker", "structured_worker", "vdeflate", "structured-tool"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/rust-workers-v1")
    args = parser.parse_args()
    out = args.out.resolve()
    if (out / "build-receipt.json").exists() or (out / ".frozen").exists() or any((out / name).exists() for name in BINS):
        raise RuntimeError("existing worker seal; refusing replacement")
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE,
                                     "crates/deflate-core/src", "crates/deflate-core/Cargo.toml"], cwd=ROOT, text=True).splitlines()
    baseline_hashes = {}
    for relative in paths:
        original = subprocess.check_output(["git", "show", BASELINE + ":" + relative], cwd=ROOT)
        baseline_hashes[relative] = hashlib.sha256(original).hexdigest()
        if sha(ROOT / relative) != baseline_hashes[relative]:
            raise RuntimeError("control core differs from b7: " + relative)
    if tomllib.loads((ROOT / "Cargo.toml").read_text())["profile"]["release"] != {"opt-level": 3}:
        raise RuntimeError("release profile differs from preregistered control")
    env = os.environ.copy()
    removed = {}
    for key in list(env):
        if key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER") or key.startswith("CARGO_PROFILE_RELEASE_"):
            removed[key] = env.pop(key)
    out.mkdir(parents=True, exist_ok=True)
    command = ["cargo", "+1.88.0", "build", "--locked", "--release", "-p", "new-methods-bench",
               "-p", "vdeflate", "-p", "structured-codec", "--features", "structured-codec/cli"]
    with (out / "build.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    binaries = {}
    for name in BINS:
        shutil.copy2(ROOT / "target/release" / name, out / name)
        binaries[name] = {"sha256": sha(out / name), "bytes": (out / name).stat().st_size}
    baseline_seal = json.loads((ROOT / "scripts/reports/new-methods-baseline-seal.json").read_text())
    # Baseline seal layout is independent of this worker receipt.
    baseline_cli = ROOT / "target/new-methods/baseline-b7/cli"
    if baseline_cli.exists() and sha(out / "vdeflate") != sha(baseline_cli):
        raise RuntimeError("default CLI binary differs from sealed b7")
    inputs = [ROOT / "Cargo.toml", ROOT / "Cargo.lock", ROOT / "rust-toolchain.toml"]
    for directory in ("tools/new-methods-bench", "crates/structured-codec"):
        inputs += sorted((ROOT / directory).rglob("*.rs"))
        inputs.append(ROOT / directory / "Cargo.toml")
    result = {"schema_version": 1, "status": "built; shared worker contract validation required",
              "baseline_revision": BASELINE, "baseline_core_sha256": baseline_hashes,
              "baseline_seal_schema_version": baseline_seal["schema_version"],
              "default_cli_identity": "byte-identical b7 when its local sealed binary is available",
              "command": command, "removed_environment": removed,
              "rustc": subprocess.check_output(["rustc", "+1.88.0", "-vV"], text=True),
              "inputs_sha256": {str(path.relative_to(ROOT)): sha(path) for path in inputs}, "binaries": binaries,
              "context": "fresh codec state and output allocation each call; reusable mode explicitly reports fresh-no-reuse-adapter",
              "decoder_scope": "core/miniz tooling drivers charge exact member consumption and known size; public core suffix behavior unchanged"}
    (out / "build-receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "binaries": binaries}, indent=2))


if __name__ == "__main__":
    main()
