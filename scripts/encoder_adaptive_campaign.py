#!/usr/bin/env python3
"""P4 regional search and repetition-predictor training/validation pilots."""
import argparse
from pathlib import Path

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT
from encoder_parse_campaign import run


def methods():
    return [f"adaptive:{light}:{stop}:{index}:0:0:16" for light in (4,16) for stop in (4,8,16) for index in ("trigram","dual")] + [
        f"adaptive:4:8:trigram:{samples}:0:16" for samples in (4096,16384,65536)]


def corrected_methods():
    return [f"adaptive-entropy:4:8:trigram:{samples}:0:16" for samples in (4096,16384,65536)]


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--binary",type=Path,default=ROOT/"target/encoder-performance/p4-build/release/examples/final_bench")
    parser.add_argument("--real",type=Path,default=CORPUS_OUT)
    parser.add_argument("--synthetic",type=Path,default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline",type=Path,default=BASELINE_OUT)
    parser.add_argument("--partition",choices=("train","validation"),default="train")
    parser.add_argument("--rounds",type=int,default=1)
    parser.add_argument("--minimum-ms",type=int,default=5)
    parser.add_argument("--methods",nargs="+",default=methods())
    args=parser.parse_args()
    run(args.out.resolve(),args.binary.resolve(),args.real.resolve(),args.synthetic.resolve(),args.baseline.resolve(),args.partition,args.rounds,args.minimum_ms,args.methods,
        allowed_methods=methods()+corrected_methods(),inspector="--adaptive-inspect",run_oracle=False,extra_sources=(Path(__file__),),label="P4 adaptive")
