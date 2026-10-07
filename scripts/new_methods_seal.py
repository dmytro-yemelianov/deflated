#!/usr/bin/env python3
"""Preserve the immutable b7 build independently of ongoing research edits."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "b7d5e0fc79f4f72d2ba772312ec9a22497699ed5"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, cwd=ROOT, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/baseline-b7")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("refusing to replace an existing baseline; verify its seal instead")
    out.mkdir(parents=True)
    archive = out / "source.tar"
    subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), REVISION],
                   cwd=ROOT, check=True)
    source = out / "source"
    source.mkdir()
    subprocess.run(["tar", "-xf", str(archive), "-C", str(source)], check=True)
    env = os.environ.copy()
    # Build environment is explicit; record caller settings instead of quietly
    # inheriting experimental RUSTFLAGS, wrappers or an alternate target dir.
    overrides = {k: env.pop(k) for k in list(env)
                 if k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER",
                          "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_TARGET", "CARGO_TARGET_DIR")
                 or k.startswith("CARGO_PROFILE_RELEASE_")
                 or (k.startswith("CARGO_") and k.endswith("_RUSTFLAGS"))}
    builds = [
        ("cli", ["--workspace"], out / "cli-build", "release/vdeflate"),
        ("default_worker", ["-p", "deflate-core", "--example", "default_bench"],
         out / "default-build", "release/examples/default_bench"),
        ("research_worker", ["-p", "deflate-core", "--example", "final_bench",
                             "--features", "research-tuning"],
         out / "research-build", "release/examples/final_bench"),
    ]
    binaries = {}
    for label, options, directory, relative in builds:
        command = ["cargo", "build", "--locked", "--release", "--target-dir", str(directory), *options]
        completed = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True)
        (out / (label + ".build.log")).write_text(completed.stdout + completed.stderr)
        completed.check_returncode()
        binary = out / label
        shutil.copy2(directory / relative, binary)
        binaries[label] = {"path": str(binary.relative_to(out)), "sha256": sha(binary),
                           "bytes": binary.stat().st_size, "command": command}
    sources = {str(p.relative_to(source)): sha(p) for p in sorted(source.rglob("*")) if p.is_file()}
    receipt = {"schema_version": 1, "revision": REVISION, "archive_sha256": sha(archive),
               "sources": sources, "binaries": binaries, "rustc": run(["rustc", "-Vv"]),
               "cargo": run(["cargo", "-V"]), "host": platform.platform(),
               "removed_environment": overrides, "effective_rustflags": [],
               "release_profile": {"opt-level": 3},
               "status": "built and hashed; packet equivalence validation is a separate G0 gate"}
    (out / "seal.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"seal": str(out / "seal.json"), "binaries": binaries}, indent=2))


if __name__ == "__main__":
    main()
