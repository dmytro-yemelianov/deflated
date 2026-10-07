#!/usr/bin/env python3
"""Freeze/audit the decoder-only supplement to the immutable G0 reference lock."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import subprocess

from encoder_corpus import ROOT, digest, write_json

REPORTS = ROOT / "scripts/reports"
LOCK = REPORTS / "new-methods-decoder-lock.json"


def check(local=False):
    value = json.loads(LOCK.read_text())
    assert value["v1_reference_lock_sha256"] == digest((REPORTS / "new-methods-reference-lock.json").read_bytes())
    for path, expected in value["evidence_sha256"].items():
        assert digest((ROOT / path).read_bytes()) == expected, path
    build = json.loads((REPORTS / "new-methods-decoder-build.json").read_text())
    contracts = json.loads(gzip.decompress((REPORTS / "new-methods-decoder-contracts.json.gz").read_bytes()))
    ledger = json.loads((REPORTS / "new-methods-decoder-ledger.json").read_text())
    for path, expected in build["inputs_sha256"].items():
        assert digest((ROOT / path).read_bytes()) == expected, path
    assert contracts["tool_sha256"] == digest((ROOT / "scripts/test_new_methods_decoder_workers.py").read_bytes())
    assert value["lock_tool_sha256"] == digest(Path(__file__).read_bytes())
    assert contracts["status"] == "passed" and contracts["timer_contracts"] == 292 and contracts["rejected_cases"] == 584
    assert contracts["build_sha256"] == digest((REPORTS / "new-methods-decoder-build.json").read_bytes())
    assert ledger["compile_checks_cumulative"] == 6 and ledger["contract_fix_rounds_cumulative"] == 2
    expected_hashes = {row["codec"]: row["binary_sha256"] for row in build["native"]}
    expected_hashes.update({codec: row["sha256"] for codec, row in build["rust"].items()})
    assert all(row["binary_sha256"] == expected_hashes[row["codec"]] for row in contracts["rows"])
    subprocess.run(["python3", "scripts/new_methods_reference_lock.py", "--check", *(["--local"] if local else [])], cwd=ROOT, check=True)
    if local:
        out = ROOT / value["workers"]
        assert (out / ".frozen").read_text().strip() == digest(LOCK.read_bytes())
        for row in build["native"]:
            assert digest((out / row["codec"]).read_bytes()) == row["binary_sha256"]
        for row in build["rust"].values():
            assert digest((ROOT / row["path"]).read_bytes()) == row["sha256"]
        assert digest((ROOT / "target/new-methods/native-workers-v1/native_crc32_table.h").read_bytes()) == build["table_sha256"]
    print("Decoder-only supplement source/build/contract lock validated" + (" including local binaries" if local else ""))


def freeze(out):
    names = ["new-methods-decoder-build.json", "new-methods-decoder-contracts.json.gz", "new-methods-decoder-ledger.json", LOCK.name]
    if any((REPORTS / name).exists() for name in names) or (out / ".frozen").exists():
        raise ValueError("decoder supplement already frozen; refusing replacement")
    contracts = json.loads((out / "contracts.json").read_text())
    assert contracts["status"] == "passed" and contracts["build_sha256"] == digest((out / "build.json").read_bytes())
    shutil.copy2(out / "build.json", REPORTS / names[0])
    (REPORTS / names[1]).write_bytes(gzip.compress((out / "contracts.json").read_bytes(), mtime=0))
    ledger = json.loads((out / "ledger.json").read_text())
    ledger["status"] = "compiled and decoder-only contracts passed; before study screening"
    write_json(REPORTS / names[2], ledger)
    value = {"schema_version": 1, "status": "frozen before any study measurement", "workers": str(out.relative_to(ROOT)),
             "v1_reference_lock_sha256": digest((REPORTS / "new-methods-reference-lock.json").read_bytes()),
             "lock_tool_sha256": digest(Path(__file__).read_bytes()),
             "evidence_sha256": {"scripts/reports/" + name: digest((REPORTS / name).read_bytes()) for name in names[:-1]},
             "timing": "cold decode supplies only resident compressed packet; no preceding encoder/decoder. Warm decode pays fresh state, output allocation/destruction and checksums. No startup/IO or guessed subtraction.",
             "scope": "same sealed v1 codec and framing routines; separate decoder-only executable layout. Existing v1 cold first_decode_ns follows encoding and is not used as fully cold decode."}
    write_json(LOCK, value)
    (out / ".frozen").write_text(digest(LOCK.read_bytes()) + "\n")
    check(local=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/decode-workers-v1")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    if args.check:
        check(args.local)
    else:
        freeze(args.out)
