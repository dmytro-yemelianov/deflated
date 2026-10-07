#!/usr/bin/env python3
"""Compare the same frozen selector in feature/local/exact execution modes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, write_json
from encoder_parse_campaign import run
from encoder_selector import choose, VOCABULARY
from search_poc import decode_exact


def methods(policy):
    return [prefix+str(policy) for prefix in ("policy@","policy-local@","policy-exact@")]


def verify_training_choices(binary, teacher, out):
    result=json.loads((teacher/"result.json").read_text())
    policy=teacher/"selector.policy"
    if hashlib.sha256(policy.read_bytes()).hexdigest()!=result["policy_sha256"]:
        raise ValueError("frozen policy changed")
    evidence=[]
    for c in json.loads((teacher/"matrix.json").read_text()):
        k=choose(result["fitted"]["tree"],c)
        raw_path=Path(c["input"]); raw=raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=c["raw_sha256"]:raise ValueError("changed teacher input")
        expected=c["measurements"][k]["candidate_sha256"]
        local_expected=expected
        if k==1 and len(raw)>=32768:
            packet=out/"local-reference.deflate"
            subprocess.run([str(binary),"--memory",str(raw_path),str(packet),"adaptive:16:16:dual:0:0:16"],check=True,stdout=subprocess.DEVNULL,timeout=120)
            decode_exact(packet.read_bytes(),raw); local_expected=hashlib.sha256(packet.read_bytes()).hexdigest()
        exact_expected=expected if c["measurements"][k]["packed_bytes"]*100<=c["baseline_bytes"]*101 else c["baseline_sha256"]
        for method,expected_sha in zip(methods(policy),(expected,local_expected,exact_expected)):
            packet=out/"selected.deflate"
            subprocess.run([str(binary),"--memory",str(raw_path),str(packet),method],check=True,stdout=subprocess.DEVNULL,timeout=120)
            data=packet.read_bytes(); decode_exact(data,raw)
            observed=hashlib.sha256(data).hexdigest()
            if observed!=expected_sha: raise ValueError("native selector choice differs from Python/frozen leaf")
            evidence.append({"case":c["id"],"method":method,"leaf":VOCABULARY[k],"expected_sha256":expected_sha,"observed_sha256":observed})
    write_json(out/"selector-choices.json",evidence)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--teacher",type=Path,required=True)
    parser.add_argument("--binary",type=Path,default=ROOT/"target/encoder-performance/p4-selector-build/release/examples/final_bench")
    parser.add_argument("--real",type=Path,default=CORPUS_OUT)
    parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--partition",choices=("train","validation"),default="train")
    parser.add_argument("--rounds",type=int,default=1)
    parser.add_argument("--minimum-ms",type=int,default=5)
    args=parser.parse_args()
    teacher=args.teacher.resolve(); policy=teacher/"selector.policy"
    names=methods(policy)
    run(args.out.resolve(),args.binary.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve(),args.partition,args.rounds,args.minimum_ms,names,
        allowed_methods=names,inspector="--selector-inspect",run_oracle=False,
        extra_sources=(Path(__file__),ROOT/"scripts/encoder_selector.py",ROOT/"scripts/search_policy.py",policy,teacher/"result.json",teacher/"matrix.json"),label="P4 selector")
    if args.partition=="train":verify_training_choices(args.binary.resolve(),teacher,args.out.resolve())
