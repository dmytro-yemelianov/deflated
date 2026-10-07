#!/usr/bin/env python3
"""P4 bounded CPU selector: source-group CV and fully charged native adapters.

Fit only on training. Real time is the first loss component; all other time
breaks ties. Every leaf must respect 1% aggregate bytes in each scope and
20% per file. Those training constraints are not unseen-input guarantees.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, write_json
from encoder_measure import sha
from encoder_parse_campaign import cases, sources
from search_poc import decode_exact
from search_policy import features as original_features

VOCABULARY = ["balanced", "config:16:1:0:trigram:16384", "best", "stored"]
DEPTHS = [-1, 0, 1, 2]
SEED = 20261007


def features(raw):
    """Independent Python counterpart, checked against native training features."""
    if len(raw) < 32768 or len(raw) >= 2**32:
        return original_features(raw) + [0, 0]
    tags = [None] * 32768
    histogram = [0] * 256
    word, samples, repeats = 0x19510401, 0, 0
    stride = max(len(raw)//4096, 1)
    for start in range(0, len(raw)-3, stride):
        word ^= word << 13 & 0xffffffff
        word ^= word >> 17
        word ^= word << 5 & 0xffffffff
        pos = start + word % stride
        if pos > len(raw)-4:
            break
        tag = int.from_bytes(raw[pos:pos+4], "little")
        slot = ((tag * 0x1e35a7bd) & 0xffffffff) >> 17
        previous = tags[slot]
        repeats += previous is not None and previous[0] == tag and pos-previous[1] <= 32768
        tags[slot] = tag, pos
        histogram[raw[pos]] += 1
        samples += 1
    stored = samples >= 2048 and repeats*256 < samples and sum(n>0 for n in histogram) >= 240 and max(histogram)*50 <= samples
    return original_features(raw) + [repeats*4096//samples if samples else 0, int(stored)]


def scope_summary(cases_, choices):
    scopes = {}
    for scope in sorted({c["scope"] for c in cases_}):
        selected = [(c, c["measurements"][k]) for c,k in zip(cases_, choices) if c["scope"] == scope]
        scopes[scope] = {
            "speed_vs_balanced": sum(c["baseline_ns"] for c,_ in selected)/sum(r["encode_ns"] for _,r in selected),
            "size_vs_balanced": sum(r["packed_bytes"] for _,r in selected)/sum(c["baseline_bytes"] for c,_ in selected),
            "worst_file_size_ratio": max(r["packed_bytes"]/c["baseline_bytes"] for c,r in selected)}
    feasible = all(s["size_vs_balanced"] <= 1.01 and s["worst_file_size_ratio"] <= 1.2 for s in scopes.values())
    return {"scopes": scopes, "feasible": feasible, "choices": choices}


def choose(tree, case):
    if case["raw_bytes"] < 32768:
        return 0
    while "config" not in tree:
        tree = tree["left" if case["features"][tree["feature"]] <= tree["threshold"] else "right"]
    return tree["config"]


def leaf(cases_):
    eligible = []
    for k in range(len(VOCABULARY)):
        choices = [0 if c["raw_bytes"] < 32768 else k for c in cases_]
        if not scope_summary(cases_, choices)["feasible"]:
            continue
        rows = [(c, c["measurements"][n]) for c,n in zip(cases_, choices)]
        score = (sum(r["encode_ns"] for c,r in rows if c["scope"] == "new-real-train"),
                 sum(r["encode_ns"] for _,r in rows))
        eligible.append((score, k))
    if not eligible:
        raise ValueError("Balanced must make every leaf feasible")
    score, k = min(eligible)
    return {"config": k}, score


def fit(cases_, depth):
    if depth == -1:
        return {"config": 0}
    tree, loss = leaf(cases_)
    if depth == 0 or len(cases_) < 6:
        return tree
    best = None
    for axis in range(15):
        values = sorted({c["features"][axis] for c in cases_})
        for lower, upper in zip(values, values[1:]):
            threshold = (lower+upper)/2
            left = [c for c in cases_ if c["features"][axis] <= threshold]
            right = [c for c in cases_ if c["features"][axis] > threshold]
            if min(len(left), len(right)) < 3 or min(len({c["group"] for c in x}) for x in (left,right)) < 2:
                continue
            l, r = leaf(left)[1], leaf(right)[1]
            cost = (l[0]+r[0], l[1]+r[1])
            key = cost, axis, threshold
            if cost < loss and (best is None or key < best[0]):
                best = key, left, right
    if best is None:
        return tree
    (_,axis,threshold), left,right = best
    return {"feature":axis,"threshold":threshold,"left":fit(left,depth-1),"right":fit(right,depth-1)}


def folds(cases_, seed):
    groups = sorted({c["group"] for c in cases_})
    if len(groups) < 3:
        raise ValueError("three independent source groups required")
    random.Random(seed).shuffle(groups)
    assignment = {g:i%3 for i,g in enumerate(groups)}
    return [[c for c in cases_ if assignment[c["group"]] == i] for i in range(3)]


def select_depth(cases_):
    groups = folds(cases_, SEED)
    evaluations = []
    for depth in DEPTHS:
        held, choices = [], []
        for i, test in enumerate(groups):
            train = [c for j,other in enumerate(groups) if j != i for c in other]
            tree = fit(train, depth)
            held.extend(test)
            choices.extend(choose(tree,c) for c in test)
        result = scope_summary(held,choices)
        real = result["scopes"]["new-real-train"]
        evaluations.append({"depth":depth, **result, "objective":1/real["speed_vs_balanced"]})
    selected = min(evaluations, key=lambda e:(not e["feasible"],e["objective"],e["depth"]))
    return selected["depth"], evaluations


def nested(cases_):
    groups = folds(cases_, SEED+1)
    held, choices, evidence = [], [], []
    for i,test in enumerate(groups):
        train = [c for j,other in enumerate(groups) if j != i for c in other]
        depth, inner = select_depth(train)
        tree = fit(train,depth)
        selected = [choose(tree,c) for c in test]
        held.extend(test); choices.extend(selected)
        evidence.append({"fold":i,"train_groups":sorted({c["group"] for c in train}),
            "held_groups":sorted({c["group"] for c in test}),"depth":depth,"inner":inner,"tree":tree,
            "held_ids":[c["id"] for c in test],"result":scope_summary(test,selected)})
    depth, inner = select_depth(cases_)
    return {"outer":evidence,"nested_result":scope_summary(held,choices),"depth":depth,"inner":inner,"tree":fit(cases_,depth)}


def serialize(tree):
    nodes = []
    def visit(node):
        index = len(nodes); nodes.append(None)
        if "config" in node:
            nodes[index] = "L " + VOCABULARY[node["config"]]
        else:
            left,right = visit(node["left"]), visit(node["right"])
            nodes[index] = f'B {node["feature"]} {node["threshold"]!r} {left} {right}'
        return index
    visit(tree)
    return "policy-v2 features-15 short-balanced-32768\n" + "\n".join(nodes) + "\n"


def collect(out, binary, real, synthetic, baseline, minimum):
    if minimum < 1: raise ValueError("positive minimum batch required")
    selected = cases(real,synthetic,"train")
    seal = check_baseline(baseline)
    if subprocess.check_output(["rustc","--version"],text=True).strip() != seal["rustc"]:
        raise ValueError("compiler differs from sealed original")
    overrides = {k:v for k,v in os.environ.items() if k.startswith("CARGO_PROFILE_") or k in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS")}
    if overrides != seal["build_overrides"]: raise ValueError("build flags differ from original")
    out.mkdir(parents=True,exist_ok=False)
    frozen = {"sources":{**sources(),str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__)),
        "scripts/search_policy.py":sha(ROOT/"scripts/search_policy.py")},"binary":sha(binary),
        "baseline":sha(baseline/"baseline.json"),"real":sha(real/"manifest.json"),"synthetic":sha(synthetic/"manifest.json"),
        "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"build_overrides":overrides}
    write_json(out/"protocol.json",{"frozen":frozen,"vocabulary":VOCABULARY,"depths":DEPTHS,"seed":SEED,
        "minimum_ms":minimum,"training_only":True,"cases":selected,"loss":"real encode time first, total encode time breaks ties",
        "training_constraints":"each scope <=1.01 aggregate bytes; each file <=1.20 bytes",
        "groups":"real source lineage; synthetic family including paired transforms; old family",
        "variants":["feature-only","regional replacement of config16 leaf","exact 1% baseline comparison"]})
    started = time.perf_counter()
    matrix = []
    with (out/"measurements.jsonl").open("w") as log:
        for i,case in enumerate(selected):
            raw = Path(case["raw_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != case["sha256"]: raise ValueError("changed input")
            native = json.loads(subprocess.check_output([str(binary),"--selector-features",case["raw_path"]],text=True,timeout=120))
            if native != features(raw): raise ValueError("native/Python feature disagreement")
            rows = []
            for n in range(len(VOCABULARY)):
                k = (n+i)%len(VOCABULARY)
                method = VOCABULARY[k]
                folder = out/"streams"
                row = json.loads(subprocess.check_output([str(baseline/"final_bench"),"warm",case["raw_path"],str(folder),str(minimum),method,str((i+n)%2)],text=True,timeout=120))
                if any(not math.isfinite(row[f]) or row[f]<=0 for f in ("encode_ns","decode_ns","baseline_encode_ns","baseline_decode_ns")):
                    raise ValueError("invalid teacher timing")
                for suffix,field in (("candidate","packed_bytes"),("baseline","baseline_bytes")):
                    packet = (folder/(suffix+".deflate")).read_bytes(); decode_exact(packet,raw)
                    if len(packet) != row[field]: raise ValueError("packet size disagreement")
                    row[suffix+"_sha256"] = hashlib.sha256(packet).hexdigest()
                row.update(input=case["raw_path"],method=method,scope=case["scope"])
                log.write(json.dumps(row,allow_nan=False)+"\n"); log.flush()
                rows.append((k,row))
            rows = [r for _,r in sorted(rows)]
            if len({r["baseline_sha256"] for r in rows}) != 1: raise ValueError("nondeterministic original Balanced")
            baseline_ns = statistics.median(r["baseline_encode_ns"] for r in rows)
            group = "real:"+case["source_group"] if case["scope"] == "new-real-train" else case["scope"]+":"+case["family"]
            matrix.append({"id":case["path"],"input":case["raw_path"],"raw_sha256":case["sha256"],"scope":case["scope"],"group":group,"features":native,"raw_bytes":len(raw),
                "baseline_bytes":rows[0]["baseline_bytes"],"baseline_ns":baseline_ns,"baseline_sha256":rows[0]["baseline_sha256"],
                "measurements":[{"packed_bytes":r["packed_bytes"],"encode_ns":r["encode_ns"]/r["baseline_encode_ns"]*baseline_ns,
                    "candidate_sha256":r["candidate_sha256"]} for r in rows]})
    native_seconds = time.perf_counter()-started
    begun = time.perf_counter(); result = nested(matrix); model_seconds = time.perf_counter()-begun
    write_json(out/"matrix.json",matrix)
    (out/"selector.policy").write_text(serialize(result["tree"]))
    if sha(binary) != frozen["binary"] or {p:sha(ROOT/p) for p in frozen["sources"]} != frozen["sources"] or check_baseline(baseline) != seal or sha(real/"manifest.json") != frozen["real"] or sha(synthetic/"manifest.json") != frozen["synthetic"]:
        raise ValueError("frozen selector sources/binary/corpus changed")
    write_json(out/"result.json",{"frozen":frozen,"fitted":result,"policy_sha256":sha(out/"selector.policy"),
        "native_seconds_including_features_and_verification":native_seconds,"cpu_model_seconds":model_seconds,
        "model_fraction_of_measured_loop":model_seconds/(native_seconds+model_seconds),"rows":len(matrix)*len(VOCABULARY),
        "limitations":["teacher leaf timings exclude feature cost; native policy verification includes it",
            "one warm pilot session; not final confidence","nested CV conditional on this frozen vocabulary; validation remains separate"]})
    print(json.dumps({"rows":len(matrix)*len(VOCABULARY),"depth":result["depth"],"model_seconds":model_seconds,"native_seconds":native_seconds}),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--real",type=Path,default=CORPUS_OUT)
    parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--minimum-ms",type=int,default=5)
    args = parser.parse_args()
    try:
        collect(args.out.resolve(),args.binary.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve(),args.minimum_ms)
    except BaseException as error:
        if args.out.is_dir(): write_json(args.out/"failed.json",{"error":str(error),"ledger":"measurements.jsonl"})
        raise
