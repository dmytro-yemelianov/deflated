# Validated parameter adapter and CPU search pilot

S1 now exposes five encoder axes behind the optional `research-tuning`
Cargo feature. The CPU runner supports seeded random search and a simple
Pareto-mutation heuristic. The first two studies verified 852 streams and
found useful synthetic speed/size tradeoffs. These settings are experimental;
no production preset has been changed or promoted.

## Parameter contract

```toml
[dependencies]
deflate-core = { path = "crates/deflate-core", features = ["research-tuning"] }
```

```rust
use deflate_core::research::{Config, Index};

let config = Config::new(64, true, 0, Index::Dual, 16384)?;
let packed = deflate_core::research::deflate(input, config);
```

`Config::new` rejects invalid values before encoding. Its fields are private;
the only entry point uses the validated configuration. The feature adds no
runtime dependency, and the core still uses `no_std` and contains no unsafe
code. Normal levels and experimental configurations share matcher insertion,
search, match acceptance and token progression through separately compiled
generic policies. The normal matcher carries no experimental fields.

| Axis | Adapter bounds | Search proposal grid |
| --- | --- | --- |
| Probes per hash chain | 1–1024 | 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024 |
| Parser | greedy or one-step lazy | both |
| Insertion tail | 0–32; zero indexes all positions | 0, 4, 8, 16, 32 |
| Index | trigram or dual three/four-byte | both |
| Block tokens | 256, 1024, 4096, 16384 | all four |

The proposal grid has **880 configurations**. Nonzero insertion tails retain
a match's start and trailing positions after sufficiently large advances;
small advances still index every valid position. Probe caps apply to each
chain, rather than a shared total across both indexes. Configured indexes
are fixed choices; production Balanced still uses its existing input
classifier. Experimental splits use the existing emitter and whole-input
stored fallback, with no Best cost-based quarter splitting.

The 32 KiB distance window and 15-bit hash tables are unchanged. Configured
table capacities are 192 KiB for trigram and 384 KiB for dual indexing. These
are analytical capacities, excluding output, emitter buffers and peak RSS;
memory has not become a measured third optimization objective.

## Running a study

```sh
python3 scripts/search_corpus.py --profile smoke
make research-check
make research-defaults

python3 scripts/search_cpu.py --strategy random --seed 195108 \
    --trials 16 --rounds 5 --min-ms 2 \
    --out target/search/cpu-random-new
python3 scripts/search_cpu.py --strategy pareto-mutation --seed 195108 \
    --trials 16 --rounds 5 --min-ms 2 \
    --out target/search/cpu-mutation-new
```

Run timing studies serially while other heavy jobs are idle. Every study
measures Fast, Balanced, Best and Stored controls plus the specified number
of unique configured trials. Pareto-mutation proposes one-axis changes to
configured nondominated parents 70% of the time and random proposals
otherwise. It is a small baseline heuristic, not NSGA-II or a Bayesian
optimizer. There are no third-party Python dependencies or GPU calls.

The worker times encoding and allocation, alternating candidate and Balanced
order across files and rounds. Disk I/O, validation and decoding are outside
encode timings. Objectives are total compressed bytes and the ratio of
summed per-file median encode times to the paired Balanced measurements.
Raw time, throughput and every round are retained; throughput is computed
from summed input bytes and summed times, not an average of file rates.

The build cache is keyed by source hashes, compiler and release flag
overrides. Provenance records these, the binary hash, corpus manifest,
hardware, seed and budgets. Each trial checks complete case membership,
finite positive paired samples, deterministic encoding and three decoders:
deflate-core, miniz_oxide and system zlib. Zlib must consume the stream
exactly. Source, binary and corpus changes abort the study.

Training determines three roles: fastest, smallest, and fastest within the
declared size tolerance (1% above training Balanced by default). Stored is
excluded from these roles. The runner writes and hashes `finalists.json`
before measuring only those unique finalists on validation. The reserved
test partition is never encoded by the runner. Failed trials retain their
ledger/provenance and abort; they receive no successful objective value.
Existing output directories are rejected, and resume is not implemented.

## First measured results

Both studies used Apple M5, Rust 1.88.0, the smoke corpus, seed 195108,
16 configured trials plus four controls, and five rounds of at least 2 ms
per candidate/baseline batch. Each measured 20 training cases and two unique
finalists on 13 validation cases: **426 verified streams per study**.

Validation totals 459008 input bytes; paired Balanced produces 207257 bytes.
All figures below describe this synthetic validation split only.

| Study and role | Configuration | Packed bytes | Size vs Balanced | Encode speed vs paired Balanced |
| --- | --- | ---: | ---: | ---: |
| Random speed/compromise | 1 probe, lazy, tail 32, trigram, 16384 tokens | 206259 | −0.48% | 1.67× |
| Random size | existing Best preset | 205040 | −1.07% | 0.42× |
| Mutation speed/compromise | 2 probes, greedy, tail 16, trigram, 16384 tokens | 206180 | −0.52% | 1.59× |
| Mutation size | 256 probes, lazy, all positions, trigram, 16384 tokens | 203604 | −1.76% | 0.70× |

Whole-loop elapsed times were 12.34 s for random search and 11.46 s for
mutation, including 0.99 s and 0.03 s of build work respectively. Cache state
differs, so these wall times cannot establish which strategy is better.
The candidate and paired baseline encode rounds, configs, source/binary
hashes and aggregate results are retained in
[`search-cpu-spike.json`](../scripts/reports/search-cpu-spike.json) and its
hash-linked [raw ledger](../scripts/reports/search-cpu-measurements.jsonl).
Packed streams and complete trial directories remain under `target/search/`.
The recorded Git commit is the parent before this adapter was committed;
the source hash maps identify the actual code measured in both studies.

The size finalist from mutation illustrates a separate compression target:
smaller output costs about 44% more encode time than its paired Balanced.
The speed finalists improve both measured axes on validation, while their
training sizes remain within the declared 1% tolerance. This is a useful
signal for further investigation, not evidence of universal superiority.

## Verification and next decision

`make research-defaults` compared **232 feature-enabled preset streams**
across training, validation and stress with pre-adapter SHA-256 hashes from
commit `232678d`. All bytes matched and all three decoders passed. This is
a finite regression witness; an intentional future preset promotion may
update the gate. The 14 reserved test cases were not encoded.

An ordinary build without the feature was also compared with commit
`232678d` using identical benchmark source, three alternating process pairs
and five inner rounds on the four existing 8 MiB synthetic inputs. Balanced
aggregate throughput was 1.008× the earlier build; individual multiples
ranged from 0.995× to 1.029×, and all output sizes matched. These short
regression observations do not establish a speed improvement. The report
retains every process result, binary/input hashes and the aggregation rule.

Feature tests cover invalid settings, 24 matcher corner combinations on
mixed/periodic/window-spanning inputs, all split sizes and empty/word/window/
stored boundaries. The roundtrip fuzz target now selects ordinary levels
or a bounded experimental configuration, then verifies two decoders.
CI checks feature-enabled and ordinary builds and the preset byte gate.
The Lean model is unchanged; its acceptance and emitter proof scope still
applies, while these Rust configuration tests are not a formal proof of the
entire adapter implementation.

Local gates passed: 189 ordinary and 192 feature-enabled Rust tests,
15 research-tool integrity tests, 104 headline theorem axiom checks,
20197 differential streams under three oracles, 1654 framing checks,
format/Clippy checks and five 60-second fuzz runs with no findings.

This pilot uses one seed, a tiny synthetic corpus and short rounds. It has
no confidence intervals, measured peak memory, sensitivity attribution,
real-workload validation or comparison to tuned competitor encoders. The
validation split was already visible in phase zero, so it cannot serve as
fresh final-test evidence. Neither optimizer has demonstrated superiority.

Next: S2 interaction sweeps and the planned three-seed S3 comparison on a
larger training set, then frozen real-workload validation and memory costs.
Keep separate speed, compression and compromise finalists. Fit a surrogate
and consider GPU proposals after enough CPU observations establish a useful
prediction baseline; the earlier GPU kernel result alone cannot justify an
end-to-end GPU search claim.

The follow-up S2/S3 campaign is recorded in
[cpu-search-campaign-report.md](cpu-search-campaign-report.md). It preserves
this first pilot as historical evidence rather than replacing its timings.
