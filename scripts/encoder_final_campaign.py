#!/usr/bin/env python3
"""P5: explicit pre-test freeze, serial original/candidate pairs, tiny and RSS.

prepare hashes/copies inputs but never encodes held data or computes features.
measure requires that complete freeze and never builds or tunes a candidate.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tarfile
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, validate, write_json
from encoder_measure import inputs, sha
from encoder_parse_campaign import sources as encoder_sources
from search_corpus import validate as validate_synthetic
from search_final_campaign import parse_rss, schedule
from search_poc import decode_exact

TINY_SIZES = [0,1,2,3,4,15,31,64,255,257,258,259,1024,4096]


def source_hashes():
    names = ["scripts/encoder_final_campaign.py", "scripts/encoder_final_stats.py",
        "scripts/encoder_final_correspondence.py", "scripts/encoder_protocol.json",
        "scripts/search_final_campaign.py", "scripts/search_final_stats.py", "scripts/search_cpu.py",
        "crates/deflate-core/examples/default_bench.rs", "lean-toolchain",
        "crates/vdeflate/Cargo.toml", "scripts/reports/encoder-p5-portable-size.json"]
    names += [f"scripts/reports/encoder-final-{role}.policy" for role in ("speed","compromise","size")]
    names += [str(p.relative_to(ROOT)) for directory,pattern in (("spec","*.lean"),("crates/vdeflate/src","*.rs"))
              for p in sorted((ROOT/directory).rglob(pattern))]
    return {**encoder_sources(), **{name:sha(ROOT/name) for name in names}}


def selected_cases(real, synthetic, out, contract):
    real_meta=json.loads((real/"manifest.json").read_text()); validate(real,real_meta)
    synthetic_meta=json.loads((synthetic/"manifest.json").read_text()); validate_synthetic(synthetic,synthetic_meta)
    if sha(real/"manifest.json")!=contract["corpus_manifest_sha256"] or sha(synthetic/"manifest.json")!=contract["synthetic_manifest_sha256"]:
        raise ValueError("held manifests differ from the original contract")
    records=[]
    for prefix,root,meta,scope in (("real",real,real_meta,"new-real-test"),("synthetic",synthetic,synthetic_meta,"new-synthetic-test")):
        for c in meta["cases"]:
            if c["partition"]=="test":records.append({**c,"source_path":str((root/c["path"]).resolve()),"path":prefix+"/"+c["path"],"scope":scope})
    records += [{**c,"source_path":c["raw_path"],"path":"regression/"+Path(c["path"]).name}
                for c in inputs(real,"train") if c["scope"]=="old-regression"]
    rng=random.Random(contract["measurement"]["seed"])
    seen=set()
    for n in TINY_SIZES:
        for family,raw in (("tiny-random",rng.randbytes(n)),("tiny-periodic",(b"abc"*(n//3+1))[:n])):
            h=hashlib.sha256(raw).hexdigest()
            if h in seen:continue
            seen.add(h)
            path=f"tiny/{family}-{n}.raw"; file=out/"corpus"/path; file.parent.mkdir(parents=True,exist_ok=True); file.write_bytes(raw)
            records.append({"path":path,"partition":"stress","scope":"tiny","family":family,"source_group":family,
                            "bytes":n,"sha256":h,"source_path":str(file.resolve())})
    for c in records:
        source=Path(c["source_path"])
        if sha(source)!=c["sha256"]:raise ValueError("changed input while preparing freeze")
        file=out/"corpus"/c["path"];file.parent.mkdir(parents=True,exist_ok=True)
        if source.resolve()!=file.resolve():shutil.copyfile(source,file)
    if sum(c["scope"]=="new-real-test" for c in records)!=8 or sum(c["scope"]=="new-synthetic-test" for c in records)!=20:
        raise ValueError("unexpected held cohort coverage")
    return records


def prepare(out, real, synthetic, baseline):
    seal=check_baseline(baseline)
    contract=json.loads((ROOT/"scripts/encoder_protocol.json").read_text())
    compiler=subprocess.check_output(["rustc","--version"],text=True).strip()
    flags={k:v for k,v in os.environ.items() if k.startswith("CARGO_PROFILE_") or k in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS")}
    if compiler!=seal["rustc"] or flags!=seal["build_overrides"]:raise ValueError("original compiler/flags required")
    out.mkdir(parents=True,exist_ok=False)
    source=source_hashes()
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    for name,h in source.items():
        committed=subprocess.check_output(["git","show",commit+":"+name],cwd=ROOT)
        if hashlib.sha256(committed).hexdigest()!=h:raise ValueError("commit measured sources before preparing: "+name)
    for label,features,example in (("candidate-research",["--features","research-tuning"],"final_bench"),("candidate-default",[],"default_bench")):
        target=out/(label+"-build")
        process=subprocess.run(["cargo","build","--locked","--release","-p","deflate-core","--example",example,*features,"--target-dir",str(target)],cwd=ROOT,text=True,capture_output=True)
        (out/(label+".build.log")).write_text(process.stdout+process.stderr)
        if process.returncode:raise ValueError("candidate build failed: "+label)
        shutil.copy2(target/"release/examples"/example,out/example)
    old_source=out/"original-source";old_source.mkdir()
    with tarfile.open(baseline/"source.tar.gz") as archive:archive.extractall(old_source,filter="data")
    for name,h in seal["source_sha256"].items():
        if sha(old_source/name)!=h:raise ValueError("original archived source mismatch")
    harness=ROOT/"crates/deflate-core/examples/default_bench.rs"
    shutil.copy2(harness,old_source/"crates/deflate-core/examples/default_bench.rs")
    old_target=out/"original-default-build"
    process=subprocess.run(["cargo","build","--locked","--release","-p","deflate-core","--example","default_bench","--target-dir",str(old_target)],cwd=old_source,text=True,capture_output=True)
    (out/"original-default.build.log").write_text(process.stdout+process.stderr)
    if process.returncode:raise ValueError("original default harness build failed")
    shutil.copy2(old_target/"release/examples/default_bench",out/"original_default_bench")
    shutil.copy2(baseline/"final_bench",out/"original_bench")
    if source_hashes()!=source:raise ValueError("source changed during freeze builds")
    methods={}
    for name,method in json.loads((baseline/"methods.json").read_text()).items():
        worker=method["worker"]
        if "policy" in method:
            file=out/("original-"+name+".policy");file.write_text(method["policy"])
            if sha(file)!=method["policy_sha256"]:raise ValueError("original policy changed")
            worker="policy@"+str(file)
        methods[name]={"binary":"original_bench","worker":worker,"baseline_binary":"original_bench","baseline_worker":"balanced","origin":"original control"}
    if list(methods)!=contract["controls"]:raise ValueError("control order changed")
    for role in ("speed","compromise","size"):
        file=out/(role+".policy");shutil.copy2(ROOT/f"scripts/reports/encoder-final-{role}.policy",file)
        methods["new-"+role]={"binary":"final_bench","worker":"policy@"+str(file),"baseline_binary":"original_bench",
            "baseline_worker":contract["roles"][role]["baseline"],"origin":"frozen P2/P4 combination","role":role}
    methods["core-reversal"]={"binary":"default_bench","worker":"balanced","baseline_binary":"original_default_bench","baseline_worker":"balanced",
        "origin":"actual default core; identical harness on original archived core; no research feature"}
    records=selected_cases(real,synthetic,out,contract)
    write_json(out/"manifest.json",{"cases":records,"real_manifest_sha256":sha(real/"manifest.json"),"synthetic_manifest_sha256":sha(synthetic/"manifest.json"),
        "tiny_sizes":TINY_SIZES,"tiny_scope":"shared deterministic latency/boundary stress, not independent holdout"})
    real_cases=sorted([c for c in records if c["scope"]=="new-real-test"],key=lambda c:(-c["bytes"],c["path"]))
    synthetic_cases=sorted([c for c in records if c["scope"]=="new-synthetic-test"],key=lambda c:(-c["bytes"],c["path"]))
    drift=next(c for c in synthetic_cases if c["family"]=="drift")
    collision=next(c for c in records if c["scope"]=="old-regression" and c["family"]=="collision_trigram")
    memory_real={}
    for c in real_cases:memory_real.setdefault(c["class"],c)
    memory=list(dict.fromkeys(c["path"] for c in [*memory_real.values(),synthetic_cases[0],drift,collision]))
    shutil.copy2(ROOT/"scripts/reports/encoder-p5-portable-size.json",out/"portable-size.json")
    size=json.loads((out/"portable-size.json").read_text())
    for name,path,expected in (("portable_vdeflate",ROOT/"target/encoder-performance/p5-portable-cli/release/vdeflate",size["candidate"]["binary_sha256"]),
        ("original_portable_vdeflate",ROOT/"target/encoder-performance/p5-original-cli/build/release/vdeflate",size["original"]["binary_sha256"])):
        if sha(path)!=expected:raise ValueError("actual portable CLI differs from size evidence")
        shutil.copy2(path,out/name)
    (out/"source.tar.gz").write_bytes(subprocess.check_output(["git","archive","--format=tar.gz",commit],cwd=ROOT))
    artifacts=["final_bench","default_bench","original_default_bench","original_bench","manifest.json","portable-size.json","source.tar.gz","portable_vdeflate","original_portable_vdeflate"]
    artifacts += [p.name for p in out.glob("*.policy")]+[p.name for p in out.glob("*.build.log")]
    frozen={"schema":1,"contract":contract,"contract_sha256":sha(ROOT/"scripts/encoder_protocol.json"),"source_commit":commit,"source_sha256":source,
        "artifacts":{name:sha(out/name) for name in artifacts},"methods":methods,"rss_cases":memory,"rustc":compiler,"build_overrides":flags,
        "original_source_archive_sha256":sha(baseline/"source.tar.gz"),"original_default_harness_sha256":sha(harness),"baseline_metadata_sha256":sha(baseline/"baseline.json"),
        "baseline_path":str(baseline),"real_path":str(real),"synthetic_path":str(synthetic),
        "prepared_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"held_encoded_before_freeze":False,"held_features_before_freeze":False}
    write_json(out/"freeze.json",frozen)
    print(json.dumps({"frozen":str(out/"freeze.json"),"cases":len(records),"methods":len(methods),"source_commit":commit}),flush=True)


def guard(out, frozen):
    if source_hashes()!=frozen["source_sha256"]:raise ValueError("frozen source changed")
    if any(sha(out/name)!=h for name,h in frozen["artifacts"].items()):raise ValueError("frozen artifact changed")
    check_baseline(Path(frozen["baseline_path"]))
    if sha(Path(frozen["baseline_path"])/"baseline.json")!=frozen["baseline_metadata_sha256"]:raise ValueError("baseline seal changed")
    if sha(Path(frozen["real_path"])/"manifest.json")!=frozen["contract"]["corpus_manifest_sha256"] or sha(Path(frozen["synthetic_path"])/"manifest.json")!=frozen["contract"]["synthetic_manifest_sha256"]:
        raise ValueError("original corpus manifest changed")
    for c in json.loads((out/"manifest.json").read_text())["cases"]:
        if sha(out/"corpus"/c["path"])!=c["sha256"]:raise ValueError("frozen input changed")


def measure(out):
    frozen=json.loads((out/"freeze.json").read_text()); frozen_sha=sha(out/"freeze.json")
    guard(out,frozen)
    if (out/"measurements.jsonl").exists() or (out/"started.json").exists():raise ValueError("run already started; do not restart or retune held results")
    write_json(out/"started.json",{"freeze_sha256":frozen_sha,"started_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
    cases=json.loads((out/"manifest.json").read_text())["cases"];methods=frozen["methods"];names=list(methods)
    measurement=frozen["contract"]["measurement"]
    signatures={};internal_signatures={};rows=[];rss=[];current={"phase":"timing"};started=time.perf_counter()
    def call(mode,case,binary,method,order,folder):
        minimum=measurement["tiny_minimum_batch_ms" if case["scope"]=="tiny" else "warm_minimum_batch_ms"]
        raw_path=out/"corpus"/case["path"];raw=raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=case["sha256"]:raise ValueError("input changed")
        row=json.loads(subprocess.check_output([str(out/binary),mode,str(raw_path),str(folder),str(minimum),method,str(order)],text=True,timeout=120))
        packet=(folder/"candidate.deflate").read_bytes();decode_exact(packet,raw)
        if len(packet)!=row["packed_bytes"] or len(raw)!=row["raw_bytes"]:raise ValueError("native byte-count mismatch")
        if any(not math.isfinite(row[f]) or row[f]<=0 for f in ("encode_ns","decode_ns")):raise ValueError("invalid native timing")
        row["packet_sha256"]=hashlib.sha256(packet).hexdigest()
        if mode=="warm" and binary in ("final_bench","original_bench"):
            base=(folder/"baseline.deflate").read_bytes();decode_exact(base,raw)
            if len(base)!=row["baseline_bytes"]:raise ValueError("internal baseline count mismatch")
            row["internal_baseline_sha256"]=hashlib.sha256(base).hexdigest()
        return row
    try:
        with (out/"measurements.jsonl").open("w") as log:
            for session in range(measurement["sessions"]):
                print("final session",session,flush=True)
                offset=session%len(cases)
                for i in list(range(offset,len(cases)))+list(range(offset)):
                    case=cases[i]
                    for index,(name,order) in enumerate(schedule(session,i,names)):
                        method=methods[name];current={"phase":"timing","session":session,"input":case["path"],"method":name}
                        write_json(out/"progress.json",{**current,"rows":len(rows),"seconds":time.perf_counter()-started})
                        warm={};cold={}
                        for mode,found in (("warm",warm),("cold",cold)):
                            for turn in range(2):
                                side=(order+turn)%2
                                if side==1 and method["origin"]=="original control" and mode=="warm":continue
                                found[side]=call(mode,case,method["binary"] if side==0 else method["baseline_binary"],
                                    method["worker"] if side==0 else method["baseline_worker"],order,out/("candidate-streams" if side==0 else "original-streams"))
                        candidate=warm[0]
                        original=warm.get(1)
                        if original is None:
                            original={"packed_bytes":candidate["baseline_bytes"],"encode_ns":candidate["baseline_encode_ns"],
                                      "decode_ns":candidate["baseline_decode_ns"],"packet_sha256":candidate["internal_baseline_sha256"]}
                        if candidate["packet_sha256"]!=cold[0]["packet_sha256"] or original["packet_sha256"]!=cold[1]["packet_sha256"]:raise ValueError("warm/first-call packet differs")
                        if "internal_baseline_sha256" in candidate and method["baseline_worker"]=="balanced" and candidate["internal_baseline_sha256"]!=original["packet_sha256"]:
                            raise ValueError("candidate changed original Balanced output")
                        if name=="core-reversal" and candidate["packet_sha256"]!=original["packet_sha256"]:raise ValueError("default core changed packets")
                        signature=(candidate["packet_sha256"],original["packet_sha256"])
                        if signatures.setdefault((name,case["path"]),signature)!=signature:raise ValueError("nondeterministic output")
                        if "internal_baseline_sha256" in candidate:internal_signatures[name,case["path"]]=candidate["internal_baseline_sha256"]
                        row={**current,"scope":case["scope"],"family":case["family"],"source_group":case.get("source_group",case.get("pair_id",case["family"])),
                            "original_case_index":i,"method_order":index,"pair_order":order,"raw_bytes":case["bytes"],"packed_bytes":candidate["packed_bytes"],"baseline_bytes":original["packed_bytes"],
                            "packet_sha256":candidate["packet_sha256"],"baseline_packet_sha256":original["packet_sha256"],
                            "encode_ns":candidate["encode_ns"],"decode_ns":candidate["decode_ns"],"baseline_encode_ns":original["encode_ns"],"baseline_decode_ns":original["decode_ns"],
                            "cold_encode_ns":cold[0]["encode_ns"],"cold_decode_ns":cold[0]["decode_ns"],"cold_baseline_encode_ns":cold[1]["encode_ns"],"cold_baseline_decode_ns":cold[1]["decode_ns"],
                            "candidate_native":candidate,"original_native":original}
                        rows.append(row);log.write(json.dumps(row,allow_nan=False)+"\n");log.flush()
                    # Original default and research presets must also agree.
                    if signatures["core-reversal",case["path"]][1]!=signatures["balanced",case["path"]][0]:raise ValueError("original default/research packet mismatch")
                    if any(internal_signatures[name,case["path"]]!=signatures["balanced",case["path"]][0] for name in names if (name,case["path"]) in internal_signatures):
                        raise ValueError("a worker changed internal Balanced packets")
                guard(out,frozen)
                if sha(out/"freeze.json")!=frozen_sha:raise ValueError("freeze metadata changed")
        system=platform.system()
        for path in frozen["rss_cases"]:
            case=next(c for c in cases if c["path"]==path)
            for name,method in methods.items():
                sides=[("candidate",method["binary"],method["worker"])]
                if method["origin"]!="original control":sides.append(("baseline",method["baseline_binary"],method["baseline_worker"]))
                for side,binary,worker in sides:
                    for repeat in range(measurement["rss_repeats"]):
                        current={"phase":"RSS","input":path,"method":name,"side":side,"repeat":repeat}
                        write_json(out/"progress.json",{**current,"rows":len(rows)})
                        packet=out/"memory.deflate";raw_path=out/"corpus"/path
                        process=subprocess.run(["/usr/bin/time","-l" if system=="Darwin" else "-v",str(out/binary),"--memory",str(raw_path),str(packet),worker],capture_output=True,text=True,check=True,timeout=120)
                        decode_exact(packet.read_bytes(),raw_path.read_bytes())
                        expected=signatures[name,path][0 if side=="candidate" else 1]
                        if sha(packet)!=expected:raise ValueError("RSS packet differs from timed packet")
                        rss.append({**current,"peak_rss_bytes":parse_rss(process.stderr,system),"packet_sha256":expected,"native":json.loads(process.stdout),"stderr":process.stderr})
        write_json(out/"rss.json",rss);guard(out,frozen)
        if sha(out/"freeze.json")!=frozen_sha:raise ValueError("freeze metadata changed")
        write_json(out/"result.json",{"freeze_sha256":frozen_sha,"measurement_sha256":sha(out/"measurements.jsonl"),"rss_sha256":sha(out/"rss.json"),
            "verified_rows":len(rows),"rss_processes":len(rss),"elapsed_seconds":time.perf_counter()-started,"platform":platform.platform(),
            "cpu":subprocess.check_output(["sysctl","-n","machdep.cpu.brand_string"],text=True).strip() if system=="Darwin" else platform.processor(),
            "adaptive_test_feedback":False,"promotion":"pending full guard and verification audit"})
        print(json.dumps({"completed":str(out),"rows":len(rows),"rss":len(rss),"seconds":time.perf_counter()-started}),flush=True)
    except BaseException as error:
        write_json(out/"failure.json",{**current,"rows":len(rows),"error":str(error),"freeze_sha256":frozen_sha})
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","measure"));parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--real",type=Path,default=CORPUS_OUT);parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    args=parser.parse_args()
    if args.action=="prepare":prepare(args.out.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve())
    else:measure(args.out.resolve())
