# P0/P1: refreshed Rust encoder profiles

Status: real-corpus contract, original controls and initial profiling complete.
Subsequent synthetic construction and implementation experiments are tracked
in [the P2 report](encoder-speed-spikes.md).

The original S9 worker is sealed at commit `14f15e63e1a8955c5cfebf869ce065f29dd950fc`,
including its exact binary, source archive, compiler/flags and both policy payloads.
The new corpus has 24 declared independent source groups, eight per split,
covering six content classes in every split. Hashes and aligned-chunk checks
reject copies; publisher URLs, pinned Git commits where applicable, license
snapshots and extraction ranges are recorded. Each input is a complete file
up to 1 MiB or its recorded first 1 MiB. The eight new final-test inputs have
not been encoded or used for selector features.

The warm pilot has five paired sessions, 11 original methods and 11 inputs:
eight new training sources and three known S9 outliers (605 rows). Encoder
allocations/selection/emission are timed; I/O and three-decoder validation
are excluded. It is training evidence, not final-test promotion evidence.

| Original method | Warm speed vs paired Balanced | Packed-size change | Worst file growth |
| --- | ---: | ---: | ---: |
| balanced | 0.997× | +0.000% | +0.00% |
| bayesian-compromise | 1.472× | +3.878% | +13.65% |
| bayesian-size | 0.755× | -0.031% | +0.09% |
| bayesian-speed | 1.964× | +10.348% | +43.83% |
| best | 0.496× | -0.481% | +0.00% |
| fast | 1.331× | +4.959% | +16.25% |
| miniz1 | 6.451× | +15.135% | +56.99% |
| miniz6 | 1.122× | +1.435% | +7.23% |
| miniz9 | 0.598× | +1.289% | +6.99% |
| policy-size | 0.542× | -0.481% | +0.00% |
| policy-speed | 1.243× | +0.749% | +3.30% |

## Sampling and attribution

Apple M5, rustc 1.88.0, release O3 with line tables. Four methods × 11 inputs
give 44 two-second profiles. The profiling worker contains an encoder-only
loop; its packets match the sealed original worker and warm ledger. The
sampler does not run any decoder. Raw traces remain under
`target/encoder-performance/profile-train-v1/` with hashes in the report.

`atos -i` resolves 1648 unique binary addresses. Inclusive accounting takes
the union of inline frames and sampled ancestors; these percentages overlap.
Exclusive accounting records the innermost frame. A separate additive
nearest-encoder-caller view attributes inlined standard-library operations
and library calls to their closest core/reference caller. A generic type
argument containing `deflate_core` does not make a standard-library function
a core function. Anonymous closure names can still combine multiple sites.

The following shares use that caller view, weighted by the pilot's unprofiled
per-file median encode times, rather than giving every two-second trace equal
weight. These are sampled cost estimates, not confidence intervals.

| Method | Matcher | Bit writer | Dynamic emission/frequencies | Huffman construction |
| --- | ---: | ---: | ---: | ---: |
| balanced | 78.88% | 10.89% | 6.96% | 1.41% |
| best | 75.90% | 5.40% | 9.21% | 4.74% |
| bayesian-compromise | 67.66% | 16.43% | 10.78% | 1.73% |

The dominant cost is matching, with code writing a useful secondary target.
Best spends more time in search and frequency/Huffman work. The miniz6
reference spends about 45% in `find_match`, 33% in `compress_normal` and
15% in `read_u16_le` under the same weighted attribution. Its token-search
choices differ; sample shares alone do not explain an absolute speed ratio.

## Selected P2 implementation spikes

1. Replace the per-bit loop in `BitWriter::write_code` with bounded bit
   reversal. Preserve every width, clamp and bit-offset behavior, including
   width zero/32. Check against the scalar bit-emission semantics before
   timing. This function is about 6.2% of Balanced and 9.5% of compromise.
2. Reduce matcher iteration/bounds bookkeeping while preserving candidate
   order, probe budgets and token semantics. `Matcher::next` and chain
   traversal are major costs; inspect closure sites/counters if needed
   before choosing a rewrite. Existing bulk insertion is not a new spike.
3. Simplify accepted-match range checks using already established bounds,
   retaining full candidate byte validation. `accept` is about 7.1% of
   Balanced on the real set, 13.6% on Chinook and 22.5% on the old sampling
   trap. Include invalid indices, overflow boundaries and overlap witnesses.

No production optimization is promoted by this report. Extra research counters
are deferred until narrowing an ambiguous matcher cost requires them. The
new corpus's old compromise gives 1.472× speed but +3.878% bytes, so parameter
tuning alone has not met the main 1.5×/+1% target on these training files.

## Limitations and reproduction

This pilot has no first-call confidence, RSS or final integrated size results.
Sampling includes startup/priming/packet-write samples and loop-clock overhead;
these must not be treated as production encoder hotspots. Source-line
attribution and one trace per pair are approximate. Only this M5 workload
is measured. Old S9 outliers are regression evidence, not a fresh holdout.

[Corpus metadata](../scripts/reports/encoder-corpus.json),
[baseline report](../scripts/reports/encoder-baseline-train.json),
[raw paired ledger](../scripts/reports/encoder-baseline-train-measurements.jsonl.gz)
and [profile evidence](../scripts/reports/encoder-profile.json) retain the
inputs, hashes, source/build provenance, samples and weighting components.

```sh
python3 scripts/encoder_baseline.py --check
python3 scripts/encoder_corpus.py --check
python3 scripts/test_encoder_tools.py
python3 scripts/encoder_measure.py --out target/encoder-performance/baseline-train-NEW
CARGO_PROFILE_RELEASE_DEBUG=line-tables-only cargo build --locked --release -p deflate-core --example final_bench --features research-tuning --target-dir target/encoder-performance/profiling-build
python3 scripts/encoder_profile.py --out target/encoder-performance/profile-train-NEW
python3 scripts/encoder_profile_report.py --profiles target/encoder-performance/profile-train-NEW --baseline target/encoder-performance/baseline-train-NEW
```
