#!/usr/bin/env python3
"""Serial paired native builds vs the sealed original; no new test encoding."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import subprocess
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, write_json
from encoder_measure import inputs, sha
from search_final_campaign import parse_rss
from search_poc import decode_exact

METHODS = ["balanced", "best", "bayesian-speed", "bayesian-compromise", "policy-speed", "policy-size"]


def aggregate(rows, cases, builds, methods):
    scopes = sorted({c["scope"] for c in cases})
    results = {}
    for scope in scopes:
        table = {}
        selected = [c for c in cases if c["scope"] == scope]
        for variant in builds:
            table[variant] = {}
            for name in methods:
                reference, original_method, candidate, ratios = [], [], [], []
                for case in selected:
                    found = [r for r in rows if r["variant"] == variant and r["method"] == name and r["input"] == case["raw_path"]]
                    if not found:
                        raise ValueError("missing measured pair")
                    candidate.append(statistics.median(r["candidate"]["encode_ns"] for r in found))
                    original_method.append(statistics.median(r["original"]["encode_ns"] for r in found))
                    reference.append(statistics.median(r["original"]["baseline_encode_ns"] for r in found))
                    ratios.append(statistics.median(r["candidate"]["encode_ns"] / r["original"]["encode_ns"] for r in found))
                table[variant][name] = {"speed_vs_original_same_method": sum(original_method)/sum(candidate),
                    "speed_vs_original_balanced": sum(reference)/sum(candidate), "packed_change_from_same_method_pct": 0,
                    "worst_input_median_time_ratio": max(ratios), "raw_bytes": sum(c["bytes"] for c in selected)}
        results[scope] = table
    return results


def tiny_cases(out):
    rng, cases, seen = random.Random(20261007), [], set()
    for size in [0,1,2,3,4,15,16,17,257,258,259]:
        for family, raw in (("random", rng.randbytes(size)), ("periodic", (b"abc"*((size+2)//3))[:size])):
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            file = out / "tiny" / (family + "-" + str(size) + ".raw")
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
            cases.append({"raw_path":str(file), "source_group":family+str(size), "scope":"tiny", "bytes":size, "sha256":digest})
    return cases


def run(out, build_path, corpus, baseline, partition, rounds, minimum, names, with_aux):
    out = out.resolve()
    if rounds < 1 or minimum < 1 or not names or any(n not in METHODS for n in names):
        raise ValueError("invalid measurement options")
    seal = check_baseline(baseline)
    builds = json.loads(build_path.read_text())
    compiler = subprocess.check_output(["rustc", "--version"], text=True).strip()
    for name, build in builds.items():
        if sha(Path(build["binary"])) != build["binary_sha256"] or build["identity"]["rustc"] != compiler:
            raise ValueError("variant binary/compiler changed: " + name)
    cases = inputs(corpus, partition)
    methods = json.loads((baseline / "methods.json").read_text())
    out.mkdir(parents=True, exist_ok=False)
    if with_aux:
        cases += tiny_cases(out)
    frozen = {"builds_sha256":sha(build_path), "baseline_sha256":sha(baseline / "baseline.json"),
              "corpus_manifest_sha256":sha(corpus / "manifest.json"), "driver_sha256":sha(Path(__file__))}
    protocol = {"cases":cases, "builds":builds, "methods":names, "frozen":frozen,
                "partition":partition,"rounds":rounds,"minimum_ms":minimum,"tiny_minimum_ms":2,
                "purpose":"isolated semantic-equivalence pilot; original and candidate builds paired serially"}
    write_json(out / "protocol.json", protocol)
    pairs = [(v,m) for v in builds for m in names]
    rows, current = [], None
    started = time.perf_counter()

    def call(binary, case, method, order, folder):
        raw = Path(case["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != case["sha256"]:
            raise ValueError("input changed")
        minimum_ms = 2 if case["scope"] == "tiny" else minimum
        data = json.loads(subprocess.check_output([str(binary),"warm",case["raw_path"],str(folder),str(minimum_ms),method,str(order)],text=True,timeout=120))
        for suffix, field in (("candidate","packed_bytes"),("baseline","baseline_bytes")):
            packet = (folder / (suffix+".deflate")).read_bytes()
            decode_exact(packet,raw)
            if len(packet) != data[field] or len(raw) != data["raw_bytes"]:
                raise ValueError("worker byte counts differ")
            data[suffix+"_sha256"] = hashlib.sha256(packet).hexdigest()
        for field in ("encode_ns","baseline_encode_ns","decode_ns","baseline_decode_ns"):
            if not math.isfinite(data[field]) or data[field] <= 0:
                raise ValueError("invalid native time")
        return data

    try:
        with (out / "measurements.jsonl").open("w") as log:
            for session in range(rounds):
                print("comparison session",session,flush=True)
                offset = session % len(cases)
                for original_index in list(range(offset,len(cases)))+list(range(offset)):
                    case = cases[original_index]
                    rotation = (session+original_index)%len(pairs)
                    for pair_index,(variant,name) in enumerate(pairs[rotation:]+pairs[:rotation]):
                        order = (session+original_index+pairs.index((variant,name)))%2
                        current = {"session":session,"variant":variant,"method":name,"input":case["raw_path"],"scope":case["scope"]}
                        observed = {}
                        for turn in range(2):
                            side = (order+turn)%2
                            binary = Path(builds[variant]["binary"]) if side==0 else baseline/"final_bench"
                            observed[side] = call(binary,case,methods[name]["worker"],order,out/("candidate-streams" if side==0 else "original-streams"))
                        for field in ("candidate_sha256","baseline_sha256","packed_bytes","baseline_bytes"):
                            if observed[0][field] != observed[1][field]:
                                raise ValueError("variant changed packet: "+variant+":"+name+":"+field)
                        for suffix in ("candidate","baseline"):
                            if (out/"candidate-streams"/(suffix+".deflate")).read_bytes()!=(out/"original-streams"/(suffix+".deflate")).read_bytes():
                                raise ValueError("variant bytes differ")
                        row = {**current,"method_order":pair_index,"pair_order":order,"candidate":observed[0],"original":observed[1]}
                        rows.append(row)
                        log.write(json.dumps(row,allow_nan=False)+"\n")
                        log.flush()
        rss=[]
        if with_aux:
            training=inputs(corpus,"train",outliers=False)
            chosen=[next(c for c in training if c.get("source_group")==group) for group in ("llvm","zlib-archive","chinook")]
            # Auxiliary memory-only cases are always training inputs, including
            # when the timing stage uses the disjoint validation sources.
            system=platform.system()
            for case in chosen:
                raw=Path(case["raw_path"]).read_bytes()
                for variant,build in {"original":{"binary":str(baseline/"final_bench")},**builds}.items():
                    for name in names:
                        for repeat in range(3):
                            current={"phase":"RSS","variant":variant,"method":name,"case":case["source_group"],"repeat":repeat}
                            packet=out/"memory.deflate"
                            cmd=["/usr/bin/time","-l" if system=="Darwin" else "-v",build["binary"],"--memory",case["raw_path"],str(packet),methods[name]["worker"]]
                            process=subprocess.run(cmd,text=True,capture_output=True,check=True,timeout=120)
                            decode_exact(packet.read_bytes(),raw)
                            rss.append({**current,"peak_rss_bytes":parse_rss(process.stderr,system),"packet_sha256":sha(packet),"native":json.loads(process.stdout),"tool_stderr":process.stderr})
        if check_baseline(baseline)!=seal or sha(build_path)!=frozen["builds_sha256"] or sha(corpus/"manifest.json")!=frozen["corpus_manifest_sha256"] or sha(Path(__file__))!=frozen["driver_sha256"]:
            raise ValueError("comparison contract changed")
        for build in builds.values():
            if sha(Path(build["binary"]))!=build["binary_sha256"]:
                raise ValueError("variant changed during timing")
        result={"protocol":protocol,"rows":len(rows),"metrics":aggregate(rows,cases,builds,names),"rss":rss,
                "elapsed_seconds":time.perf_counter()-started,"raw_ledger_sha256":sha(out/"measurements.jsonl"),
                "limitations":["warm pilot; not final first-call confidence or blind-test evidence","fixed cases on one machine","zero size changes required by exact packet checks"]}
        write_json(out/"result.json",result)
        print(json.dumps({"rows":len(rows),"rss_runs":len(rss),"metrics":result["metrics"]},indent=2),flush=True)
    except BaseException as error:
        write_json(out/"failed.json",{"current":current,"rows":len(rows),"error":str(error),"frozen":frozen})
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--builds",type=Path,default=ROOT/"target/encoder-performance/p2-builds/builds.json")
    parser.add_argument("--corpus",type=Path,default=CORPUS_OUT)
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--partition",choices=("train","validation"),default="train")
    parser.add_argument("--rounds",type=int,default=5)
    parser.add_argument("--minimum-ms",type=int,default=10)
    parser.add_argument("--methods",nargs="+",default=METHODS)
    parser.add_argument("--aux",action="store_true")
    args=parser.parse_args()
    run(args.out,args.builds,args.corpus,args.baseline,args.partition,args.rounds,args.minimum_ms,args.methods,args.aux)
