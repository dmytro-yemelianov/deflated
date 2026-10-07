#!/usr/bin/env python3
"""Build decoder-only timing supplement without changing the sealed v1 workers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

from encoder_corpus import ROOT, digest, write_json
from new_methods_native_build import CODECS, LIBRARIES


def sha(path):
    return digest(path.read_bytes())


def build(out, references):
    if out.exists():
        raise ValueError("decoder build requires a fresh directory; preserve prior attempts")
    subprocess.run(["python3", "scripts/new_methods_reference_lock.py", "--check", "--local"], cwd=ROOT, check=True)
    ledger = json.loads((ROOT / "scripts/reports/new-methods-native-implementation-ledger.json").read_text())
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    assert ledger["compile_checks_used"] + 1 <= protocol["budgets"]["native_adapter_compile_checks_max"]
    assert ledger["contract_fix_rounds_used"] + 1 <= protocol["budgets"]["native_adapter_contract_fix_rounds_max"]
    out.mkdir(parents=True)
    local_ledger = {"schema_version": 1, "status": "started", "utc": datetime.now(timezone.utc).isoformat(),
                    "previous_ledger_sha256": sha(ROOT / "scripts/reports/new-methods-native-implementation-ledger.json"),
                    "compile_checks_cumulative": ledger["compile_checks_used"] + 1,
                    "contract_fix_rounds_cumulative": ledger["contract_fix_rounds_used"] + 1,
                    "note": "Sixth C compile check / second contract-fix round: decoder-only cold/warm supplement, before screening",
                    "study_screening_started": False}
    write_json(out / "ledger.json", local_ledger)
    table = ROOT / "target/new-methods/native-workers-v1/native_crc32_table.h"
    rows = []
    for index, (codec, libraries) in enumerate(zip(CODECS, LIBRARIES), 1):
        directory = (references / codec).resolve()
        receipt = json.loads((directory / "build-receipt.json").read_text())
        for relative, expected in receipt["libraries"].items():
            assert sha(directory / relative) == expected
        prefix = directory / "install"
        binary = out.resolve() / codec
        command = ["clang", "-std=c11", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-function", f"-DNATIVE_CODEC={index}", "-I", str(prefix / "include"),
                   "-I", str(table.parent), str(ROOT / "scripts/native_decode_worker.c"),
                   "-L", str(prefix / "lib"), f"-Wl,-rpath,{prefix / 'lib'}",
                   *["-l" + lib for lib in libraries], "-o", str(binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        (out / (codec + ".build.log")).write_text(result.stdout + result.stderr)
        result.check_returncode()
        rows.append({"codec": codec, "command": command, "binary_sha256": sha(binary),
                     "binary_bytes": binary.stat().st_size, "library_hashes": receipt["libraries"],
                     "linkage": subprocess.check_output(["otool", "-L", str(binary)], text=True)})
    package = ROOT / "tools/new-methods-decode"
    env = os.environ.copy()
    removed = {}
    for key in list(env):
        if key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER") or key.startswith("CARGO_PROFILE_RELEASE_"):
            removed[key] = env.pop(key)
    command = ["cargo", "+1.88.0", "build", "--manifest-path", str(package / "Cargo.toml"), "--release", "--locked", "--offline"]
    with (out / "rust.build.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    rust = {}
    for codec, name in (("core", "core_decode"), ("miniz", "miniz_decode"), ("dsc1", "structured_decode")):
        shutil.copy2(package / "target/release" / name, out / name)
        rust[codec] = {"path": str((out / name).relative_to(ROOT)), "sha256": sha(out / name), "bytes": (out / name).stat().st_size}
    inputs = [ROOT / "scripts/native_decode_worker.c", ROOT / "scripts/native_codec_worker.c",
              ROOT / "scripts/new_methods_decoder_build.py", package / "Cargo.toml", package / "Cargo.lock",
              ROOT / "Cargo.toml", ROOT / "Cargo.lock", ROOT / "rust-toolchain.toml"]
    inputs += sorted((package / "src").rglob("*.rs"))
    # v1 lock audits the included adapter, core and structured implementation inputs.
    result = {"schema_version": 1, "status": "built; contracts pending", "v1_reference_lock_sha256": sha(ROOT / "scripts/reports/new-methods-reference-lock.json"),
              "inputs_sha256": {str(p.relative_to(ROOT)): sha(p) for p in inputs}, "table_sha256": sha(table),
              "native": rows, "rust": rust, "rust_command": command, "removed_environment": removed,
              "clang": subprocess.check_output(["clang", "--version"], text=True),
              "rustc": subprocess.check_output(["rustc", "+1.88.0", "-vV"], text=True),
              "mode": "resident packet, fresh decoder state each call, no preceding encoder; IO/startup excluded"}
    write_json(out / "build.json", result)
    local_ledger["status"] = "compiled; independent contracts pending"
    write_json(out / "ledger.json", local_ledger)
    print(json.dumps({"native": len(rows), "rust": len(rust), "compile_checks_cumulative": local_ledger["compile_checks_cumulative"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/decode-workers-v1")
    parser.add_argument("--references", type=Path, default=ROOT / "target/new-methods/references-v1")
    args = parser.parse_args()
    build(args.out, args.references)
