#!/usr/bin/env python3
"""Replay every new P5 case packet through actual Lean/Rust CLI decoders."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from encoder_final_campaign import guard
from encoder_corpus import ROOT, write_json
from encoder_measure import sha
from search_poc import decode_exact

sys.path.insert(0,str(ROOT/"oracles"))
from differential import LEAN, RUST, run_oracle


def run(out):
    frozen=json.loads((out/"freeze.json").read_text());guard(out,frozen)
    result=json.loads((out/"result.json").read_text())
    if sha(out/"measurements.jsonl")!=result["measurement_sha256"]:raise ValueError("timed ledger changed")
    rows=[json.loads(line) for line in (out/"measurements.jsonl").read_text().splitlines()]
    expected={(r["method"],r["input"]):r["packet_sha256"] for r in rows}
    methods=frozen["methods"];records=[]
    for case in json.loads((out/"manifest.json").read_text())["cases"]:
        raw_path=out/"corpus"/case["path"];raw=raw_path.read_bytes()
        packets=[];batch=[]
        for name in ("new-speed","new-compromise","new-size","core-reversal"):
            method=methods[name];packet=out/"correspondence.deflate"
            subprocess.check_output([str(out/method["binary"]),"--memory",str(raw_path),str(packet),method["worker"]],timeout=120)
            data=packet.read_bytes();decode_exact(data,raw)
            if sha(packet)!=expected[name,case["path"]]:raise ValueError("correspondence packet differs from timing")
            packets.append(data);batch.append({"input":case["path"],"method":name,"raw_bytes":len(raw),"raw_sha256":case["sha256"],"packet_sha256":sha(packet)})
        # Bounded per-case batches avoid retaining the whole corpus as hex.
        lean=run_oracle([str(LEAN)],packets);rust=run_oracle([str(RUST),"--oracle"],packets)
        for record,model,native in zip(batch,lean,rust):
            for label,decoded in (("Lean",model),("Rust",native)):
                if not decoded.ok or len(decoded.data)!=len(raw) or hashlib.sha256(decoded.data).hexdigest()!=case["sha256"]:
                    raise ValueError(label+" decoder disagreement: "+case["path"])
            records.append({**record,"lean_decoded_sha256":case["sha256"],"rust_decoded_sha256":case["sha256"]})
        print("model correspondence",case["path"],len(records),flush=True)
    guard(out,frozen)
    write_json(out/"correspondence.json",{"records":records,"packets":len(records),"freeze_sha256":sha(out/"freeze.json"),
        "lean_binary_sha256":sha(LEAN),"rust_binary_sha256":sha(RUST),"lean_toolchain":(ROOT/"lean-toolchain").read_text().strip(),
        "checker_sha256":sha(Path(__file__)),"scope":"finite timed P5 packets on all held real/synthetic, old regression and tiny cases; not Rust refinement or a performance proof"})


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--campaign",type=Path,required=True)
    run(parser.parse_args().campaign.resolve())
