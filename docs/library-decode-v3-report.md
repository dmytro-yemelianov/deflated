# Buffered token decoder — 2026-10-14

The decoder retains unused bits from its bounded lookahead across tokens. On
six pinned real files, fresh-output throughput improves from 619.7 to 664.4 MB/s
for raw DEFLATE (+7.2%) and from 493.9 to 521.7 MB/s for gzip (+5.6%), relative
to the exact v2 binary. Both native references remain faster on this corpus.
Some packets regress; this iteration is a measured tradeoff, not a competitive
release or universal improvement claim.

## Implementation and selection

The [v2 profile](../scripts/reports/library-decode-v3-profile.txt) attributes
about 79% of top-of-stack samples to the block loop and 8% to Huffman table
construction on `Properties.lean` compressed by libdeflate. Inlining limits the
precision of this attribution.

A successful eight-byte lookahead provides at least 57 actual input bits. A
complete table-hit token needs at most 42 (12-bit literal/length code, five
length extras, 12-bit distance code, thirteen distance extras). The loop now
shifts the buffered word after each token and refills when fewer than 42 known
bits remain. It updates the logical reader after every token, and discards the
cache before scalar fallback. No speculative bits are consumed on a table miss,
reserved symbol or short input. Output limits and error precedence are unchanged.
The Rust API, dependencies and portable safe-Rust requirement are unchanged.

Three candidates were screened against v2: bit buffering, two literals per load,
and constant-sized short non-overlapping copies. Bit buffering was retained;
the literal-pair and short-copy alternatives were removed. Screening receipts
and variant sources, including negative results, are in the
[screening archive](../scripts/reports/library-decode-v3-screening.json.gz).
The expanded synthetic corpus was used during selection and is therefore
**development data**, not independent validation in this iteration.

The final source/binary freeze precedes real-file acquisition and evaluation;
no production source was retuned after those results. The controller verifies
that freeze before measuring and checks source, binary and manifest stability
at completion. The [v2 source snapshot](../scripts/reports/library-decode-v2-core-sources.json.gz)
preserves the exact uncommitted baseline sources for reconstruction.

## Fresh paired measurements

All measurements ran serially on the same macOS arm64 host with Rust 1.88.0,
zlib-ng 2.3.3 and libdeflate 1.26. Each method decodes the same packets, with
fresh output allocation and decoder state charged inside the timer. Native
gzip APIs include native checksum work. Inputs are resident; file I/O is outside
timing. This does not measure streaming, reusable decoder contexts or peak memory.

| Corpus / format | v2 MB/s | v3 MB/s | Speedup | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Real files / raw | 619.7 | 664.4 | 1.072× | 1027.7 | 1577.7 |
| Real files / gzip | 493.9 | 521.7 | 1.056× | 943.3 | 1552.5 |
| Repository / raw | 876.7 | 932.5 | 1.064× | 1568.2 | 2437.7 |
| Repository / gzip | 644.6 | 685.7 | 1.064× | 1367.0 | 2382.1 |
| Original synthetic / raw | 17534.6 | 16903.2 | 0.964× | 23805.0 | 21505.8 |
| Original synthetic / gzip | 2196.9 | 2180.9 | 0.993× | 7709.1 | 17011.3 |
| Expanded synthetic / raw | 588.2 | 722.0 | 1.227× | 1017.9 | 1440.4 |
| Expanded synthetic / gzip | 475.9 | 561.3 | 1.179× | 932.6 | 1419.6 |

Throughput is total raw bytes divided by summed per-packet median decode times.
Every file/encoder/level contributes; these are not averages of file throughputs.
The real-file raw aggregate remains 1.55× behind zlib-ng and 2.37× behind
libdeflate; gzip remains 1.81× and 2.98× behind, respectively.

## Real-file scope and regressions

The fixed roster contains Go runtime source, CommonMark specification text,
Inter variable font, OpenTelemetry metrics JSON, Kubernetes OpenAPI JSON and
Vega Seattle weather CSV. Whole files range from 4,134 to 879,708 bytes.
All six come from **previous historical training lineages**; no historical
validation/test partition was opened. They broaden the diagnostic but do not
satisfy the independent release-corpus gate. Source and license/provenance files
are verified against pinned Git blobs. Their URLs, commits, hashes and inherited
license metadata are retained in the manifest; raw bodies stay under `target/`.

Each file is compressed by zlib, zlib-ng and libdeflate at levels 1, 6 and 9,
in raw and gzip framing. Five rotated sessions yield 2,160 timing rows over
108 packets and 1,512 malformed/contract rejection checks.

| File | Raw v2 → v3 MB/s | Gzip v2 → v3 MB/s |
| --- | ---: | ---: |
| Go source | 592.1 → 608.5 | 471.0 → 479.3 |
| CommonMark text | 838.7 → 882.8 | 621.9 → 642.4 |
| Inter font | 371.5 → 407.2 | 323.7 → 349.5 |
| OpenTelemetry JSON | 546.3 → 581.4 | 444.5 → 467.9 |
| Kubernetes JSON | 1809.5 → 1828.2 | 1030.1 → 1048.3 |
| Weather CSV | 806.2 → 835.5 | 610.1 → 632.6 |

Aggregating each session separately gives raw speedups of 1.039–1.088× and gzip
speedups of 1.020–1.057×. These ranges describe repeatability on these fixed
files and this host; they are not confidence intervals over application workloads.

Individual packets can regress despite faster per-file aggregates. The worst
real packet is Go gzip encoded by zlib at level 1: 560,970 → 598,360 ns (+6.7%
time). The original diagnostic's worst is periodic raw zlib: 17,401 → 19,397 ns
(+11.5%). Expanded numeric CSV raw zlib level 1 is 0.925× as fast (+8.1% time).
Tiny raw `hello` also regresses by a few nanoseconds. All rows are retained;
there is no all-input no-regression claim.

Receipts: [real files](../scripts/reports/library-decode-v3-real.json.gz),
[original diagnostic](../scripts/reports/library-decode-v3.json.gz),
[expanded diagnostic](../scripts/reports/library-decode-v3-expanded.json.gz).
The latter two contain 840 and 1,152 rows, respectively. The final linked
benchmark executable remains 497,968 bytes, identical in size to v2 on this host.

## Correctness and reproduction

The canonical bit-at-a-time reference checks exact results, errors, consumed
bits and partial output. An additional witness interleaves short literal runs
with fifteen-bit codes to force cache invalidation, across all bit offsets,
truncations and every output limit through the run. Existing tests cover match
extras, reserved codes, overlap and container suffixes. These are finite Rust
test claims, not a new Lean refinement proof.

`make test` passes, including the Lean axiom gates, 20,197 differential streams
with zero findings and 1,654 framing checks. All-feature workspace tests,
Clippy with warnings denied, formatting, eight benchmark-evidence tests and
local Cargo package verification pass. The historical source, reference and
decoder receipt audits also pass.
Bounded fuzzing completed 5,528,077 inflate, 971,640 differential, 180,128 roundtrip runs (46 seconds per target), with no crash discovered.
[Validation logs and source hashes](../scripts/reports/library-decode-v3-validation.json.gz)
retain the evidence.

Use fresh output directories. Restore the baseline snapshot in a separate
checkout for reconstruction; an exact historical binary hash may depend on its
original build path. The local archived baseline is verified against the v2
receipt. Each final receipt embeds the candidate freeze; extract that object
as `freeze.json` to enforce the exact recorded candidate locally.

```sh
cargo build --locked --release -p deflate-core --example library_decode
python3 scripts/library_real_corpus.py --out target/library-v3/reproduce-corpus
python3 scripts/library_bench.py measure --workers target/library-v1/workers \
  --baseline target/library-v3/baseline_decode \
  --baseline-receipt scripts/reports/library-decode-v2.json.gz \
  --candidate-freeze target/library-v3/candidate-freeze.json \
  --corpus-manifest target/library-v3/reproduce-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v3/reproduce-real --sessions 5 --study library-decode-v3-real
python3 scripts/test_library_bench.py
make test
```

Reference acquisition/build steps remain in the [library plan](library-roadmap.md).
For a rebuilt candidate whose binary hash differs, record a new source/binary
freeze instead of rewriting these historical receipts. Next work remains table
construction/reusable contexts, gzip checksum costs, independent application
corpora, multi-MiB cases, x86-64 and memory measurements.
