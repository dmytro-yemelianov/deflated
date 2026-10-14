# Library decode v7: next-action lookahead and short copies

On the same six-file arm64 development corpus, v7 improves raw DEFLATE
throughput by **9%** and gzip by **7–8%** against the frozen selected v6 worker.
Both native references remain faster. This is another measured step toward the
library goal, not a competitive release claim or an independent evaluation.

## What changed

The private batch loop now reads the next packed literal/length action before
copying a match. This gives the table load independent output work to overlap.
The cached action consumes no input and is replaced after a refill whenever
too few real bits remain for a token. Invalid distances and table misses still
leave the current token for the checked fallback.

For distances of at least eight, two unconditional eight-byte copies precede
the continuation loop. Matches of length three through sixteen need no copy
loop. Each word is copied separately, preserving overlapping matches at
distances eight through fifteen. The existing initialized 264-byte output guard
covers both the sixteen-byte minimum copy and the rounded maximum match. Short
matches can write up to thirteen padding bytes; only the logical prefix is
history, and the caller truncates padding before returning.

Production changes are confined to [block.rs](../crates/deflate-core/src/block.rs).
The public API, compact fixed-block path, table representation, CRC and
allocation strategy are unchanged. There are no new runtime dependencies or
architecture intrinsics; the core retains `no_std` + `alloc` and forbids unsafe
code. The [verification boundary](verification-boundary.md) distinguishes these
tested Rust changes from the unchanged Lean model.

## Why this change

Eighteen serial exact-worker profiles revisited Go, Inter and Otel, raw and gzip,
across v6, zlib-ng and libdeflate. Each sampled two seconds of a four-second
reused-state loop; every output hash matched. The v6 block-loop leaf accounts
for 94.9% of Go raw samples and 92.1% of Inter raw samples. Go gzip spends
16.5% in the now out-of-line CRC loop; output initialization is around 1%.

A separate v6 release build with line tables provides inline attribution:

| Inclusive category | Go raw | Inter raw | Go gzip |
|---|---:|---:|---:|
| Batch loop | 94.5% | 92.3% | 76.1% |
| Match copy | 33.9% | 11.5% | 30.7% |
| Packed lookup | 9.0% | 19.4% | 6.7% |
| CRC loop | — | — | 19.2% |

These categories overlap. Sampled instruction addresses are not hardware stall
counters and do not prove that a particular instruction caused the sampled cost.
The loop still dominates; the earlier [native source/AST audit](native-decode-audit.md)
identified the next-entry load before match copying in libdeflate. V7 adapts
that ordering to the existing safe, bounded Rust loop.

Two short screens explored the initial copies alone and then the combination
with next-action lookahead. The first suggested roughly 2.5% raw improvement;
the combination suggested about 9%. These are exploratory results. Final claims
below use a separate frozen candidate and independent measurement runs on the
same development inputs, not an unseen corpus.

## Frozen comparisons

Six pinned real files, three encoders and levels 1/6/9 produce 108 raw/gzip
packets. Five rotated serial sessions use at least 20 ms per timed batch.
Every implementation receives identical bytes, checks gzip checksums and uses
the same fresh/reuse mode. Throughput is total bytes divided by the sum of
per-packet median times. Builds, profilers, tests and fuzzers do not run alongside
these final timers.

| Context | Frame | v6 MB/s | v7 MB/s | zlib-ng 2.3.3 | libdeflate 1.26 | v7/v6 |
|---|---|---:|---:|---:|---:|---:|
| Fresh | Raw | 828.7 | 903.4 | 1026.8 | 1579.0 | 1.090× |
| Fresh | Gzip | 687.5 | 735.1 | 944.7 | 1550.6 | 1.069× |
| Reuse | Raw | 802.1 | 874.2 | 978.5 | 1510.4 | 1.090× |
| Reuse | Gzip | 643.3 | 694.3 | 874.5 | 1442.1 | 1.079× |

The remaining native raw throughput ratios are **1.12–1.14×** for zlib-ng and
**1.73–1.75×** for libdeflate. Gzip ratios are 1.26–1.29× and 2.08–2.11×.
Absolute rates differ between sessions and contexts; the improvement figures
compare paired v6/v7 workers within each run.

All six file-level pooled rates improve in both modes and frames. Reused raw
gains range from 4.0% on Otel to 14.6% on Kubernetes; Go and CommonMark gain
12–13%, Inter 7.2%, and weather CSV 8.0%. Individual packet medians include
regressions: reused Go/zlib-ng-6 raw is 2.0% slower, and fresh Otel/libdeflate-1
gzip is 1.4% slower. There is no all-packet speedup claim.

Session-level pooled ratios vary: fresh raw 1.034–1.101 and gzip 1.050–1.085;
reuse raw 1.044–1.191 and gzip 0.953–1.116. In particular, one reused gzip
session is slower. The median-based totals above summarize noisy local results;
they do not establish a precise universal 9% improvement.

The broader existing synthetic diagnostic improves from 885.7 to 925.1 MB/s
raw (+4.4%) and 710.3 to 734.5 MB/s gzip (+3.4%). Its separate tiny group is
1.3% slower raw and 0.7% faster gzip. These families have already been used in
development and are not a held-out release test.

## Small inputs and size

For the zlib-encoded eleven-byte `hello world` witness, median ns/call are:

| Mode / frame | v6 | v7 | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| Fresh / raw | 41.9 | 41.4 | 125.2 | 1566.3 |
| Fresh / gzip | 61.2 | 63.1 | 143.0 | 1580.0 |
| Reuse / raw | 37.0 | 37.8 | 37.4 | 21.3 |
| Reuse / gzip | 61.6 | 61.5 | 49.0 | 25.0 |

Reused empty gzip is 42.9 → 42.8 ns. V7 does not resolve the earlier small-gzip
overhead. The large-path optimization provides no meaningful tiny-input gain.

Complete diagnostic executable sizes remain 550,224 bytes fresh and 550,448
bytes reuse on this host. These are linked executable sizes, not isolated library
size. Lookup allocations and the 8192-byte initialized batch size are unchanged;
peak memory and cross-architecture measurements remain future work.

## Correctness and evidence

An additional exhaustive copy test covers every match length 3–258, distances
1–33 and larger boundaries through 32768, nonzero padding and an untouched
sentinel beyond the 264-byte guard. Its expected output is an independent
bytewise history expansion. Existing batch tests compare exact errors, bit
positions and partial output with the public symbol decoder, which is itself
checked against canonical/bytewise decoding. They include overlapping copies,
all bit alignments, truncation, output limits and long-code fallback resumption.

`make test` passes, including the Lean axiom gate, 20,197 differential streams
across three oracles with zero findings and 1,654 framing checks. All-feature
workspace tests, Clippy with warnings denied, formatting, local Cargo package
verification and thirteen benchmark-evidence tests pass.

Five bounded fuzz runs completed 12,734,206 executions without a finding,
recorded in the validation receipt linked below.
These are finite checks, not a proof of Rust correctness.

The five final receipts contain 7,728 timed rows and 6,216 rejection checks.
Every timed batch checks exact output. All selected source and worker hashes
match their freezes; previous v1–v6 receipts and source snapshots remain intact.

- [Fresh real](../scripts/reports/library-decode-v7-real.json.gz) and
  [reuse real](../scripts/reports/library-decode-v7-reuse-real.json.gz).
- [Fresh builtin](../scripts/reports/library-decode-v7.json.gz),
  [reuse builtin](../scripts/reports/library-decode-v7-reuse.json.gz) and
  [broader synthetic](../scripts/reports/library-decode-v7-expanded.json.gz).
- [Complete source snapshot](../scripts/reports/library-decode-v7-core-sources.json.gz),
  [profiles, screens and analysis](../scripts/reports/library-decode-v7-screening.json.gz),
  and [validation receipt](../scripts/reports/library-decode-v7-validation.json.gz).

Both screen variants reconstruct exactly from the archived v6 sources plus
their retained `block.rs` overlays. Profile timings are never used as benchmark
rows. The selected candidate was frozen after tests and comments were finalized.

## Reproduction and next work

Retain the exact selected v6 workers before building v7. The local copies are
`target/library-v7/baseline-fresh` and `baseline-reuse`; their hashes match the
v6 receipts. Native builds and input manifests retain their original pins.
Use a new output directory and run without concurrent validation workloads:

```sh
cargo build --locked --release -p deflate-core --example library_decode --example library_decode_reuse
python3 scripts/library_bench.py measure --reuse \
  --workers target/library-v5/workers-final \
  --baseline target/library-v7/baseline-reuse \
  --baseline-receipt scripts/reports/library-decode-v6-reuse-real.json.gz \
  --corpus-manifest target/library-v3/real-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v7/reproduce-reuse --sessions 5
make test
python3 scripts/test_library_bench.py
```

Fresh calls omit `--reuse` and use the fresh baseline and v6 fresh receipt.
Next priorities remain the raw-loop gap, small-message setup, and a separately
designed optional hardware CRC backend. Independent corpora, x86-64 measurements
and peak-memory checks are still required before a competitive release claim.
