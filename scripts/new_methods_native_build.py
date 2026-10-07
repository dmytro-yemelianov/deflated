#!/usr/bin/env python3
"""Build one native worker per sealed reference library, then hash/link-audit it."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CODECS = ["zlib", "zlib-ng", "libdeflate", "zstd", "lz4", "brotli", "lzma2"]
LIBRARIES = [["z"], ["z-ng"], ["deflate"], ["zstd"], ["lz4"],
             ["brotlienc", "brotlidec", "brotlicommon"], ["lzma"]]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, default=ROOT / "target/new-methods/references-v1")
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/native-workers-v1")
    parser.add_argument("--check-note", required=True, help="record the bounded implementation/compiler check")
    parser.add_argument("--contract-fix", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / ".frozen").exists():
        raise RuntimeError("worker directory frozen; refusing replacement")
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    ledger_path = args.out / "implementation-ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
        "schema_version": 1, "compile_checks_used": 0, "contract_fix_rounds_used": 0,
        "checks": [], "study_screening_started": False}
    compile_cap = protocol["budgets"]["native_adapter_compile_checks_max"]
    fix_cap = protocol["budgets"]["native_adapter_contract_fix_rounds_max"]
    if ledger["study_screening_started"] or ledger["compile_checks_used"] >= compile_cap:
        raise RuntimeError("implementation/compiler budget exhausted or screening started")
    if args.contract_fix and ledger["contract_fix_rounds_used"] >= fix_cap:
        raise RuntimeError("adapter contract-fix budget exhausted")
    ledger["compile_checks_used"] += 1
    ledger["contract_fix_rounds_used"] += int(args.contract_fix)
    ledger.update(compile_checks_cap=compile_cap, contract_fix_rounds_cap=fix_cap)
    check = {"number": ledger["compile_checks_used"], "note": args.check_note,
             "status": "started", "utc": datetime.now(timezone.utc).isoformat(),
             "source_sha256": sha(ROOT / "scripts/native_codec_worker.c")}
    ledger["checks"].append(check)
    # Persist before compilation; failures consume the same bounded budget.
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    values = []
    for byte in range(256):
        value = byte
        for _ in range(8):
            value = (value >> 1) ^ (0xedb88320 if value & 1 else 0)
        values.append(f"0x{value:08x}u")
    table = args.out / "native_crc32_table.h"
    table.write_text("static const uint32_t crc_table[256] = {\n" +
                     ",\n".join(", ".join(values[i:i+8]) for i in range(0, 256, 8)) + "\n};\n")
    rows = []
    for index, (name, libraries) in enumerate(zip(CODECS, LIBRARIES), 1):
        directory = (args.references / name).resolve()
        receipt = json.loads((directory / "build-receipt.json").read_text())
        for relative, expected in receipt["libraries"].items():
            assert sha(directory / relative) == expected, (name, relative)
        prefix = directory / "install"
        binary = args.out.resolve() / name
        command = ["clang", "-std=c11", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-function", f"-DNATIVE_CODEC={index}",
                   "-I", str(prefix / "include"), "-I", str(args.out.resolve()),
                   str(ROOT / "scripts/native_codec_worker.c"), "-L", str(prefix / "lib"),
                   f"-Wl,-rpath,{prefix / 'lib'}", *[f"-l{lib}" for lib in libraries], "-o", str(binary)]
        completed = subprocess.run(command, capture_output=True, text=True)
        (args.out / (name + ".build.log")).write_text(completed.stdout + completed.stderr)
        completed.check_returncode()
        version = json.loads(subprocess.check_output([str(binary), "--version"], text=True))
        linkage = subprocess.check_output(["otool", "-L", str(binary)], text=True)
        rows.append({"codec": name, "command": command, "binary_sha256": sha(binary),
                     "binary_bytes": binary.stat().st_size, "version": version, "linkage": linkage,
                     "library_hashes": receipt["libraries"]})
    result = {"schema_version": 1, "status": "built; independent adapter validation pending",
              "source_sha256": sha(ROOT / "scripts/native_codec_worker.c"),
              "table_sha256": sha(table), "compiler": subprocess.check_output(["clang", "--version"], text=True),
              "workers": rows}
    (args.out / "build-receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    check["status"] = "passed"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    print(json.dumps({"workers": len(rows), "status": result["status"]}))


if __name__ == "__main__":
    main()
