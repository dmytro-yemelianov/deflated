#!/usr/bin/env python3
"""P4 identical-partition and regime-boundary streaming block pilots."""
import argparse
from pathlib import Path

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT
from encoder_parse_campaign import run


def methods():
    return ["stream:16384:0:0:best", "stream:16384:0:1:best", "stream:16384:256:1:best"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=ROOT/"target/encoder-performance/p4-stream-build/release/examples/final_bench")
    parser.add_argument("--real", type=Path, default=CORPUS_OUT)
    parser.add_argument("--synthetic", type=Path, default=ROOT/"target/encoder-performance/synthetic-v1")
    parser.add_argument("--baseline", type=Path, default=BASELINE_OUT)
    parser.add_argument("--partition", choices=("train", "validation"), default="train")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--minimum-ms", type=int, default=5)
    parser.add_argument("--methods", nargs="+", default=methods())
    args = parser.parse_args()
    run(args.out.resolve(), args.binary.resolve(), args.real.resolve(), args.synthetic.resolve(), args.baseline.resolve(), args.partition, args.rounds, args.minimum_ms, args.methods,
        allowed_methods=methods(), inspector="--stream-inspect", run_oracle=False,
        extra_sources=(Path(__file__), ROOT/"crates/deflate-core/examples/support/streaming_blocks.rs"), label="P4 streaming")
