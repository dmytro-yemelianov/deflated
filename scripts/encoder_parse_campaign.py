#!/usr/bin/env python3
"""P3 bounded-parser pilot: frozen recipes, actual costs and serial native pairs."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, write_json
from encoder_measure import inputs, sha
from search_cost_oracle import exact, expand, literal_bits, match_bits
from search_corpus import validate as validate_synthetic
from search_poc import decode_exact


def methods():
    return [f"bounded:{probes}:{lookahead}:{mode}:{refine}"
            for probes in (4,8,16) for lookahead in (0,1)
            for mode,refine in (("longest",0),("fixed",0),("feedback",0),("feedback",1))]


def cases(real, synthetic, partition):
    selected=inputs(real,partition)
    # The pilot's inputs() rejects the new final test before any file access.
    meta=json.loads((synthetic/"manifest.json").read_text())
    validate_synthetic(synthetic,meta)
    selected += [{**c,"raw_path":str((synthetic/c["path"]).resolve()),"scope":"new-synthetic-"+partition,
                  "source_group":c["pair_id"]} for c in meta["cases"] if c["partition"]==partition]
    return selected


def sources():
    paths=list((ROOT/"crates/deflate-core/src").glob("*.rs"))
    paths += [ROOT/p for p in ("Cargo.toml","Cargo.lock","crates/deflate-core/Cargo.toml",
        "crates/deflate-core/examples/final_bench.rs","crates/deflate-core/examples/support/final_bench.rs",
        "crates/deflate-core/examples/support/bounded_parse.rs","crates/deflate-core/examples/support/policy.rs",
        "scripts/encoder_parse_campaign.py","scripts/encoder_measure.py","scripts/encoder_corpus.py",
        "scripts/encoder_baseline.py","scripts/search_corpus.py","scripts/search_poc.py","scripts/search_cost_oracle.py")]
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}


def oracle_checks(binary, out, names):
    # Reuse all fixed-cost witnesses, without searching for preferred examples.
    prior=json.loads((ROOT/"scripts/reports/search-cost.json").read_text())["exact_rows"]
    rows=[]
    for witness in prior:
        raw=bytes.fromhex(witness["raw_hex"])
        expected=exact(raw)
        if json.loads(json.dumps(expected))!=witness["oracle"]:
            raise ValueError("independent oracle differs from preserved S7 witness")
        file=out/"oracle.raw"
        file.write_bytes(raw)
        for method in names:
            packet_dir=out/"oracle-streams"
            observed=json.loads(subprocess.check_output([str(binary),"--bounded-inspect",str(file),str(packet_dir),method],text=True,timeout=120))
            tokens=json.loads((packet_dir/"tokens.json").read_text())
            tuples=[("l",t["lit"]) if "lit" in t else ("m",t["len"],t["dist"]) for t in tokens]
            if expand(tuples)!=raw:
                raise ValueError("independent token expansion differs")
            bits=10+sum(literal_bits(t[1]) if t[0]=="l" else match_bits(t[1],t[2]) for t in tuples)
            if observed["fixed_bits"]!=bits or bits<expected["fixed_bits"]:
                raise ValueError("fixed-code accounting/optimality diagnostic failed")
            packet=(packet_dir/"candidate.deflate").read_bytes()
            fixed=(packet_dir/"fixed.deflate").read_bytes()
            decode_exact(packet,raw)
            decode_exact(fixed,raw)
            rows.append({"id":witness["id"],"raw_hex":raw.hex(),"method":method,"oracle_fixed_bits":expected["fixed_bits"],
                         "old_exhaustive_greedy_bits":witness["greedy"]["fixed_bits"],"fixed_bits":bits,
                         "tokens":tokens,"packet_hex":packet.hex(),"fixed_hex":fixed.hex(),"stats":observed})
    write_json(out/"oracle.json",rows)
    return {"pairs":len(rows),"optimal":sum(r["fixed_bits"]==r["oracle_fixed_bits"] for r in rows),
            "max_fixed_bit_gap":max(r["fixed_bits"]-r["oracle_fixed_bits"] for r in rows),"sha256":sha(out/"oracle.json")}


def summary(rows, selected, names):
    result={}
    for scope in sorted({c["scope"] for c in selected}):
        table={}
        for name in names:
            per_file=[]
            for case in selected:
                if case["scope"]!=scope:continue
                found=[r for r in rows if r["method"]==name and r["input"]==case["raw_path"]]
                if not found:raise ValueError("missing measured native pair")
                signatures={(r["candidate"]["packed_bytes"],r["candidate"]["packet_sha256"],r["original"]["baseline_bytes"],r["original"]["packed_bytes"]) for r in found}
                if len(signatures)!=1:raise ValueError("nondeterministic parser output")
                packed,_,base,best=signatures.pop()
                per_file.append({"case":case["path"],"family":case["family"],"source_group":case["source_group"],
                    "encode_ns":statistics.median(r["candidate"]["encode_ns"] for r in found),
                    "original_balanced_ns":statistics.median(r["original"]["baseline_encode_ns"] for r in found),
                    "original_best_ns":statistics.median(r["original"]["encode_ns"] for r in found),
                    "packed_bytes":packed,"original_balanced_bytes":base,"original_best_bytes":best,"size_ratio":packed/base,"best_size_ratio":packed/best})
            table[name]={"warm_speed_vs_original_balanced":sum(r["original_balanced_ns"] for r in per_file)/sum(r["encode_ns"] for r in per_file),
                "packed_size_change_pct":100*(sum(r["packed_bytes"] for r in per_file)/sum(r["original_balanced_bytes"] for r in per_file)-1),
                "warm_speed_vs_original_best":sum(r["original_best_ns"] for r in per_file)/sum(r["encode_ns"] for r in per_file),
                "packed_size_change_vs_best_pct":100*(sum(r["packed_bytes"] for r in per_file)/sum(r["original_best_bytes"] for r in per_file)-1),
                "worst_file_size_ratio":max(r["size_ratio"] for r in per_file),"files":per_file}
        result[scope]=table
    return result


def run(out,binary,real,synthetic,baseline,partition,rounds,minimum,names):
    if rounds<1 or minimum<1 or not names or len(names)!=len(set(names)) or any(n not in methods() for n in names):
        raise ValueError("invalid bounded-pilot protocol")
    selected=cases(real,synthetic,partition)
    seal=check_baseline(baseline)
    compiler=subprocess.check_output(["rustc","--version"],text=True).strip()
    if compiler!=seal["rustc"]:raise ValueError("compiler differs from original")
    overrides={k:v for k,v in os.environ.items() if k.startswith("CARGO_PROFILE_") or k in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS")}
    if overrides!=seal["build_overrides"]:raise ValueError("build flags differ from original")
    if binary.name!="final_bench" or binary.parent.name!="examples" or binary.parent.parent.name!="release":
        raise ValueError("expected target-dir/release/examples/final_bench")
    out.mkdir(parents=True,exist_ok=False)
    before=sources()
    build=subprocess.run(["cargo","build","--locked","--release","-p","deflate-core","--example","final_bench",
                          "--features","research-tuning","--target-dir",str(binary.parents[2])],cwd=ROOT,text=True,capture_output=True)
    (out/"build.log").write_text(build.stdout+build.stderr)
    if build.returncode!=0 or before!=sources():raise ValueError("build failed or sources changed during compilation")
    frozen={"source_sha256":sources(),"binary_sha256":sha(binary),"baseline_sha256":sha(baseline/"baseline.json"),
            "real_manifest_sha256":sha(real/"manifest.json"),"synthetic_manifest_sha256":sha(synthetic/"manifest.json")}
    protocol={"purpose":"P3 bounded training/validation pilot; no final-test encoding or final confidence",
              "partition":partition,"cases":selected,"methods":names,"rounds":rounds,"minimum_ms":minimum,"frozen":frozen,
              "build":{"rustc":compiler,"flags":overrides,"log_sha256":sha(out/"build.log")},
              "paired_original":"original Best; its separately timed original Balanced is the speed headline baseline"}
    write_json(out/"protocol.json",protocol)
    rows=[]
    current=None
    begun=time.perf_counter()
    try:
        print("short fixed-code diagnostics",flush=True)
        oracle=oracle_checks(binary,out,names)
        # Inspection is separate from timing. Include header/extra bits and
        # estimation errors on representative real, drift and outlier cases.
        diagnostics=[]
        diagnostic_cases=[c for c in selected if c["source_group"] in ("llvm","chinook","rust","postgresql") or c["family"] in ("drift","feature_sampling_trap")]
        for case in diagnostic_cases:
            raw=Path(case["raw_path"]).read_bytes()
            for name in names:
                current={"phase":"diagnostic","input":case["raw_path"],"method":name}
                data=json.loads(subprocess.check_output([str(binary),"--bounded-inspect",case["raw_path"],str(out/"diagnostic-streams"),name],text=True,timeout=120))
                packet=(out/"diagnostic-streams/candidate.deflate").read_bytes()
                decode_exact(packet,raw)
                if data["attempted_stream_bits"]!=data["actual_payload_bits"]+data["header_and_eob_bits"]:
                    raise ValueError("rebuilt Huffman/header accounting differs from emitted bits")
                diagnostics.append({**current,"stats":data,"packet_sha256":hashlib.sha256(packet).hexdigest()})
        write_json(out/"diagnostics.json",diagnostics)
        def call(worker,case,method,order,folder):
            raw=Path(case["raw_path"]).read_bytes()
            if sha(Path(case["raw_path"]))!=case["sha256"]:raise ValueError("changed raw input")
            data=json.loads(subprocess.check_output([str(worker),"warm",case["raw_path"],str(folder),str(minimum),method,str(order)],text=True,timeout=120))
            for suffix,field in (("candidate","packed_bytes"),("baseline","baseline_bytes")):
                packet=(folder/(suffix+".deflate")).read_bytes()
                decode_exact(packet,raw)
                if len(packet)!=data[field] or len(raw)!=data["raw_bytes"]:raise ValueError("worker byte counts differ")
                data["packet_sha256" if suffix=="candidate" else "internal_baseline_sha256"]=hashlib.sha256(packet).hexdigest()
            for field in ("encode_ns","decode_ns","baseline_encode_ns","baseline_decode_ns"):
                if not math.isfinite(data[field]) or data[field]<=0:raise ValueError("invalid native timing")
            return data
        controls=[]
        old_methods=json.loads((baseline/"methods.json").read_text())
        with (out/"measurements.jsonl").open("w") as log, (out/"controls.jsonl").open("w") as control_log:
            for session in range(rounds):
                print("parser session",session,flush=True)
                offset=session%len(selected)
                for original_index in list(range(offset,len(selected)))+list(range(offset)):
                    case=selected[original_index]
                    for control_name in ("policy-size","miniz6"):
                        current={"session":session,"input":case["raw_path"],"method":control_name,"scope":case["scope"]}
                        data=call(baseline/"final_bench",case,old_methods[control_name]["worker"],(session+original_index)%2,out/"control-streams")
                        row={**current,**data}
                        controls.append(row)
                        control_log.write(json.dumps(row,allow_nan=False)+"\n");control_log.flush()
                    rotation=(session+original_index)%len(names)
                    for name in names[rotation:]+names[:rotation]:
                        order=(session+original_index+names.index(name))%2
                        current={"session":session,"input":case["raw_path"],"method":name,"scope":case["scope"],"pair_order":order}
                        observed={}
                        for turn in range(2):
                            side=(order+turn)%2
                            observed[side]=call(binary if side==0 else baseline/"final_bench",case,name if side==0 else "best",order,out/("candidate-streams" if side==0 else "original-streams"))
                        if observed[0]["internal_baseline_sha256"]!=observed[1]["internal_baseline_sha256"]:
                            raise ValueError("current worker changed original Balanced packet")
                        row={**current,"candidate":observed[0],"original":observed[1]}
                        rows.append(row)
                        log.write(json.dumps(row,allow_nan=False)+"\n");log.flush()
        if sources()!=frozen["source_sha256"] or sha(binary)!=frozen["binary_sha256"] or check_baseline(baseline)!=seal or sha(real/"manifest.json")!=frozen["real_manifest_sha256"] or sha(synthetic/"manifest.json")!=frozen["synthetic_manifest_sha256"]:
            raise ValueError("frozen parser protocol/source/corpus changed")
        result={"protocol":protocol,"oracle":oracle,"diagnostics_sha256":sha(out/"diagnostics.json"),"rows":len(rows),"control_rows":len(controls),"controls_ledger_sha256":sha(out/"controls.jsonl"),
                "metrics":summary(rows,selected,names),"raw_ledger_sha256":sha(out/"measurements.jsonl"),"elapsed_seconds":time.perf_counter()-begun,
                "limitations":["warm pilot, not final warm/first-call confidence","no RSS/tiny/integrated size guard decision","per-block refinement check does not guarantee a global size improvement when feedback changes future parsing"]}
        write_json(out/"result.json",result)
        print(json.dumps({"rows":len(rows),"oracle":oracle,"seconds":result["elapsed_seconds"]}),flush=True)
    except BaseException as error:
        write_json(out/"failed.json",{"current":current,"rows":len(rows),"error":str(error),"frozen":frozen})
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--binary",type=Path,default=ROOT/"target/encoder-performance/p3-build/release/examples/final_bench")
    parser.add_argument("--real",type=Path,default=CORPUS_OUT)
    parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--partition",choices=("train","validation"),default="train")
    parser.add_argument("--rounds",type=int,default=3)
    parser.add_argument("--minimum-ms",type=int,default=5)
    parser.add_argument("--methods",nargs="+",default=methods())
    args=parser.parse_args()
    run(args.out.resolve(),args.binary.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve(),args.partition,args.rounds,args.minimum_ms,args.methods)
