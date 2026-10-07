#!/usr/bin/env python3
"""Bind finite worker evidence to its exact source/build hashes and roster.

This receipt audit does not reproduce native builds or prove an algorithm.
"""
import gzip
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "scripts/reports"


def read(name):
    path = REPORTS / name
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def main():
    native = read("new-methods-native-workers-build.json")
    rust = read("new-methods-rust-workers-build.json")
    nv = read("new-methods-native-worker-contracts.json.gz")
    rv = read("new-methods-rust-worker-contracts.json.gz")
    for receipt in (native, rust):
        for relative, expected in receipt["tooling_sha256"].items():
            assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    assert nv["status"] == rv["status"] == "passed"
    assert nv["binary_sha256"] == {row["codec"]: row["binary_sha256"] for row in native["workers"]}
    assert rv["binary_sha256"] == {codec: rust["binaries"][name]["sha256"] for codec, name in
                                    (("core", "core_worker"), ("miniz", "miniz_worker"), ("dsc1", "structured_worker"))}
    for relative, expected in rust["inputs_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for relative, expected in rust["baseline_core_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    baseline = read("new-methods-baseline-seal.json")
    assert rust["baseline_revision"] == baseline["revision"]
    assert rust["binaries"]["vdeflate"]["sha256"] == baseline["binaries"]["cli"]["sha256"]
    assert rv["baseline_worker_sha256"] == baseline["binaries"]["research_worker"]["sha256"]
    assert nv["success_cases"] == nv["reset_identity_cases"] == len(nv["rows"]) == 328
    assert rv["success_cases"] == rv["stateless_identity_cases"] == len(rv["rows"]) == 448
    assert nv["rejected_cases"] == 1888 and rv["rejected_cases"] == 2604
    assert nv["reuse_sample_contract_cases"] == 82 and rv["timer_contract_cases"] == 256
    assert rv["b7_packet_identity_cases"] == 84
    roster = read("new-methods-reference-sources.json")
    for worker in native["workers"]:
        assert worker["library_hashes"] == roster[worker["codec"]]["libraries"]
    settings = {row["level"] for row in rv["rows"] if row["codec"] == "dsc1" and row["framing"] == "frame"}
    assert settings == {f"{log2}/{dictionary}/{numbers}" for log2, dictionary, numbers in
                        itertools.product((16, 18), ("off", "keys", "all-quoted"), ("off", "checked-delta"))}
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    ledger = read("new-methods-native-implementation-ledger.json")
    assert ledger["compile_checks_used"] == len(ledger["checks"]) <= protocol["budgets"]["native_adapter_compile_checks_max"]
    assert ledger["contract_fix_rounds_used"] <= protocol["budgets"]["native_adapter_contract_fix_rounds_max"]
    assert ledger["study_screening_started"] is False
    print("worker receipt source/build/roster audit passed; finite evidence only")


if __name__ == "__main__":
    main()
