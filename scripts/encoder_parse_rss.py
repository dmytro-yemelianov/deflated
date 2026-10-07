#!/usr/bin/env python3
"""Separate native RSS checks for the frozen P3 training-selected sentinels."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import ROOT, write_json
from encoder_measure import sha
from encoder_parse_campaign import sources
from search_final_campaign import parse_rss
from search_poc import decode_exact


def run(study,binary,out):
    result=json.loads((study/"result.json").read_text())
    frozen=result["protocol"]["frozen"]
    if sha(binary)!=frozen["binary_sha256"] or sources()!=frozen["source_sha256"]:
        raise ValueError("P3 sources or binary changed")
    seal=check_baseline(BASELINE_OUT)
    if sha(BASELINE_OUT/"baseline.json")!=frozen["baseline_sha256"]:raise ValueError("original changed")
    methods=["bounded:4:0:longest:0","bounded:16:1:feedback:0","bounded:16:1:feedback:1"]
    real_groups={"llvm","chinook","zlib-archive"}
    cases=[c for c in result["protocol"]["cases"] if c["source_group"] in real_groups or c["path"] in ("train/collision_trigram-10-0.raw","train/random_islands-7-0.raw")]
    if len(cases)!=5:raise ValueError("RSS requires five declared training cases")
    rows=[json.loads(s) for s in (study/"measurements.jsonl").read_text().splitlines()]
    controls=[json.loads(s) for s in (study/"controls.jsonl").read_text().splitlines()]
    if sha(study/"measurements.jsonl")!=result["raw_ledger_sha256"] or sha(study/"controls.jsonl")!=result["controls_ledger_sha256"]:
        raise ValueError("paired ledger changed")
    old_methods=json.loads((BASELINE_OUT/"methods.json").read_text())
    workers={name:(binary,name) for name in methods}
    workers.update({name:(BASELINE_OUT/"final_bench",old_methods[name]["worker"]) for name in ("balanced","best","policy-size","miniz6")})
    out.mkdir(parents=True,exist_ok=False)
    system=platform.system()
    observed=[]
    for case in cases:
        raw=Path(case["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=case["sha256"]:raise ValueError("RSS input changed")
        measured=[r for r in rows if r["input"]==case["raw_path"]]
        for name,(worker,method) in workers.items():
            if name in methods:
                expected={r["candidate"]["packet_sha256"] for r in measured if r["method"]==name}
            elif name in ("balanced","best"):
                expected={r["original"]["internal_baseline_sha256" if name=="balanced" else "packet_sha256"] for r in measured}
            else:
                expected={r["packet_sha256"] for r in controls if r["input"]==case["raw_path"] and r["method"]==name}
            if len(expected)!=1:raise ValueError("missing unique timing golden packet")
            for repeat in range(3):
                packet=out/"memory.deflate"
                process=subprocess.run(["/usr/bin/time","-l" if system=="Darwin" else "-v",str(worker),"--memory",case["raw_path"],str(packet),method],text=True,capture_output=True,check=True,timeout=120)
                decode_exact(packet.read_bytes(),raw)
                if sha(packet) not in expected:raise ValueError("RSS packet differs from timing golden")
                observed.append({"method":name,"case":case["path"],"repeat":repeat,"peak_rss_bytes":parse_rss(process.stderr,system),"packet_sha256":sha(packet),"native":json.loads(process.stdout),"tool_stderr":process.stderr})
    per_method={}
    for name in workers:
        deltas=[]
        per_case=[]
        for case in cases:
            median=lambda method:statistics.median(r["peak_rss_bytes"] for r in observed if r["method"]==method and r["case"]==case["path"])
            value=median(name)
            delta=value-median("best")
            deltas.append(delta)
            per_case.append({"case":case["path"],"median_peak_rss_bytes":value,"increase_vs_original_best_bytes":delta})
        per_method[name]={"max_median_increase_vs_best_bytes":max(deltas),"cases":per_case}
    if sha(binary)!=frozen["binary_sha256"] or sources()!=frozen["source_sha256"] or check_baseline(BASELINE_OUT)!=seal:
        raise ValueError("frozen resources contract changed")
    write_json(out/"result.json",{"study_result_sha256":sha(study/"result.json"),"driver_sha256":sha(Path(__file__)),"platform":system,"cases":cases,"rss_runs":len(observed),"runs":observed,"summary":per_method,
        "note":"separate processes; three repeats; exact zlib plus packet identity to three-decoder timing goldens; RSS is not a timed benchmark"})
    print(json.dumps({"runs":len(observed),"maximum_delta_vs_best":{name:data["max_median_increase_vs_best_bytes"] for name,data in per_method.items()}}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,default=ROOT/"target/encoder-performance/p3-train-v1")
    parser.add_argument("--binary",type=Path,default=ROOT/"target/encoder-performance/p3-build/release/examples/final_bench")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    run(args.study.resolve(),args.binary.resolve(),args.out.resolve())
