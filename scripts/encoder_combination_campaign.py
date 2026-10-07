#!/usr/bin/env python3
"""P5 preparation only: selected role combinations on train/validation."""
import argparse
from pathlib import Path

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT
from encoder_parse_campaign import run


def policies():
    return [ROOT/f"scripts/reports/encoder-final-{role}.policy" for role in ("speed","compromise","size")]


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--binary",type=Path,default=ROOT/"target/encoder-performance/p5-combination-build/release/examples/final_bench")
    parser.add_argument("--real",type=Path,default=CORPUS_OUT)
    parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--partition",choices=("train","validation"),default="train")
    parser.add_argument("--rounds",type=int,default=1)
    parser.add_argument("--minimum-ms",type=int,default=5)
    args=parser.parse_args()
    names=["policy@"+str(p) for p in policies()]
    run(args.out.resolve(),args.binary.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve(),args.partition,args.rounds,args.minimum_ms,names,
        allowed_methods=names,inspector="--selector-inspect",run_oracle=False,
        extra_sources=(Path(__file__),*policies()),label="P5 role combination preparation")
