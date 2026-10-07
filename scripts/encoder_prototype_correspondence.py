#!/usr/bin/env python3
"""Finite decoder agreement for retained P3 and P4 research witnesses."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from encoder_corpus import ROOT, write_json
from encoder_measure import sha
from search_poc import decode_exact

sys.path.insert(0, str(ROOT / "oracles"))
from differential import LEAN, RUST, run_oracle


def check_batch(items, records):
    packets = [packet for _, packet, _ in items]
    lean = run_oracle([str(LEAN)], packets)
    rust = run_oracle([str(RUST), "--oracle"], packets)
    if len(lean) != len(items) or len(rust) != len(items):
        raise ValueError("incomplete oracle batch")
    for (raw, packet, record), model, native in zip(items, lean, rust):
        decode_exact(packet, raw)
        expected = hashlib.sha256(raw).hexdigest()
        for decoded in (model, native):
            if not decoded.ok or decoded.data != raw:
                raise ValueError("research packet decoder disagreement: " + str(record))
        records.append({**record, "raw_sha256": expected, "raw_bytes": len(raw),
                        "packet_sha256": hashlib.sha256(packet).hexdigest(),
                        "lean_decoded_sha256": expected, "rust_decoded_sha256": expected})


def run(out, stream):
    if out.exists():
        raise ValueError("preserve an existing correspondence record")
    witness_path = ROOT / "scripts/reports/encoder-p3-train-oracle.json.gz"
    witnesses = json.loads(gzip.decompress(witness_path.read_bytes()))
    records = []; batch = []
    for witness in witnesses:
        raw = bytes.fromhex(witness["raw_hex"])
        for form, key in (("fixed", "fixed_hex"), ("auto", "packet_hex")):
            batch.append((raw, bytes.fromhex(witness[key]), {"study": "P3", "id": witness["id"], "method": witness["method"], "form": form}))
            if len(batch) == 256:
                check_batch(batch, records); batch = []
                print("prototype P3 packets", len(records), flush=True)
    if batch:
        check_batch(batch, records)
    protocol = json.loads((stream / "protocol.json").read_text())
    result = json.loads((stream / "result.json").read_text())
    binary = stream / "final_bench"
    if sha(binary) != protocol["frozen"]["binary_sha256"] or sha(stream / "diagnostics.json") != result["diagnostics_sha256"]:
        raise ValueError("sealed streaming artifacts changed")
    if sha(stream / "measurements.jsonl") != result["raw_ledger_sha256"]:
        raise ValueError("sealed streaming ledger changed")
    cases = {c["raw_path"]: c for c in protocol["cases"]}
    diagnostics = json.loads((stream / "diagnostics.json").read_text())
    packet_path = stream / "model-correspondence.deflate"
    for witness in diagnostics:
        path = Path(witness["input"]); case = cases[str(path)]
        if sha(path) != case["sha256"]:
            raise ValueError("streaming witness input changed")
        subprocess.check_output([str(binary), "--memory", str(path), str(packet_path), witness["method"]], timeout=120)
        if sha(packet_path) != witness["packet_sha256"]:
            raise ValueError("streaming replay differs from diagnostic packet")
        check_batch([(path.read_bytes(), packet_path.read_bytes(), {"study": "P4", "input": case["path"], "method": witness["method"],
                      "structural_counts": {key: witness["stats"][key] for key in ("stored_blocks", "cross_block_matches", "matches_after_stored")}})], records)
        print("prototype P4 packet", case["path"], witness["method"], flush=True)
    write_json(out, {"records": records, "packets": len(records), "p3_witness_sha256": sha(witness_path),
        "p4_diagnostics_sha256": result["diagnostics_sha256"], "p4_binary_sha256": sha(binary),
        "p4_source_archive_sha256": sha(stream / "source.tar.gz"),
        "lean_binary_sha256": sha(LEAN), "rust_binary_sha256": sha(RUST), "checker_sha256": sha(Path(__file__)),
        "lean_toolchain": (ROOT / "lean-toolchain").read_text().strip(),
        "scope": "all 6144 P3 short fixed/auto witnesses and 21 sealed P4 diagnostics, including stored-to-compressed history; finite tests, no mixed append/refinement proof or performance claim"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stream", type=Path, default=ROOT / "target/encoder-performance/p4-stream-train-v1")
    args = parser.parse_args()
    run(args.out.resolve(), args.stream.resolve())
