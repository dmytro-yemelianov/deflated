# Library decode v6: bounded batches and packed actions

The [native source/AST audit](native-decode-audit.md) is now incorporated into
the Rust decoder. On the six-file development corpus, the selected implementation
improves pooled raw throughput by **19–21%** and gzip by **27–28%** against the
frozen v5 worker, with separate fresh and reused-state comparisons. Both native
references remain faster on this pool. These are local arm64 development results,
not an independent release qualification or an all-input speedup claim.

## Implementation

- **Bounded initialized output.** Large Huffman blocks decode into up to 8192
  initialized bytes at a time, bounded by the caller's decoded-length limit.
  A local output cursor replaces per-byte `Vec::push` in the batch. At least
  264 bytes must remain before a fast token: enough for a 258-byte match and
  at most seven bytes of copy slack. Spare capacity is never treated as
  initialized memory. The logical prefix alone is valid match history; excess
  bytes are truncated before returning or propagating an error.
- **Short copies and local bit state.** Matches at distance at least eight use
  fixed eight-byte safe slice copies. Distance one uses a fill; shorter periodic
  distances grow an already-produced prefix. Complete tokens advance a local
  bit cursor, committed when the batch exits. Long codes can fall back and resume
  within the same initialized output region, avoiding repeated initialization.
- **Packed decode actions.** Private 32-bit entries contain base, symbol, extra
  bit count and code bit count. Literal-length, distance and code-length roots
  use 12, 9 and 7 bits respectively. Checked canonical decoding handles misses;
  no subtable or padded-input assumption was introduced. Lookup allocation is
  **18.5 KiB instead of 24 KiB**, excluding canonical symbols and other state.
  The public `HuffmanTable` representation/API remains unchanged. Fresh calls
  also retain their working tables across blocks within one stream.
- **Portable CRC.** Slicing-by-16 replaces slicing-by-8 for larger updates,
  retaining eight-byte and bytewise tails. The large loop is kept out of framing
  callers so its setup does not burden short updates. There is no hardware CRC
  backend, native linkage, unsafe code or new runtime dependency.
- **Compact fixed-block path.** Fixed blocks with fewer than 64 input bytes
  available retain the existing symbol decoder. Its canonical method stays in
  its original form: factoring it through a shared helper changed code generation
  and hurt tiny-stream latency. The public low-level block API retains that
  implementation too.

The main changes are in [block.rs](../crates/deflate-core/src/block.rs),
[decode_table.rs](../crates/deflate-core/src/decode_table.rs),
[inflate.rs](../crates/deflate-core/src/inflate.rs) and
[crc32.rs](../crates/deflate-core/src/crc32.rs). `no_std` + `alloc`,
`forbid(unsafe_code)`, output clearing on errors, suffix consumption, concatenated
gzip members and independent decoder calls keep their contracts. The
[verification boundary](verification-boundary.md) explicitly distinguishes the
new packed representation from the existing Lean symbol-table theorem.

## Frozen comparisons

The same pinned six real files, three encoders and levels 1/6/9 produce 108
raw/gzip packets. Every decoder receives identical bytes; native gzip calls
include their checksums. Five rotated serial sessions use at least 20 ms per
batch. No tests, builds, fuzzers or profilers run concurrently with timers.
Initialization is included in fresh calls; every implementation reuses both
state and output in the reuse comparison. Throughput is total bytes divided
by summed per-packet median times, not the average of file rates.

| Context | Frame | v5 MB/s | v6 MB/s | zlib-ng 2.3.3 | libdeflate 1.26 | v6/v5 |
|---|---|---:|---:|---:|---:|---:|
| Fresh | Raw | 683.6 | 827.4 | 1022.7 | 1571.8 | 1.210× |
| Fresh | Gzip | 532.0 | 679.5 | 927.6 | 1529.0 | 1.277× |
| Reuse | Raw | 702.5 | 836.4 | 1036.2 | 1581.9 | 1.191× |
| Reuse | Gzip | 547.6 | 693.4 | 946.1 | 1558.2 | 1.266× |

The remaining reuse throughput gaps are approximately **1.24× / 1.89× raw**
and **1.36× / 2.25× gzip**, against zlib-ng / libdeflate respectively. The
selected candidate's real-file session ratios span 1.201–1.219 raw and
1.250–1.286 gzip in fresh mode, and 1.155–1.204 raw and 1.219–1.283 gzip with
reuse. Absolute rates vary between runs; all improvement ratios above use paired
v5 measurements from the same run.

| File | Reuse v5 raw / gzip MB/s | Reuse v6 raw / gzip MB/s |
|---|---:|---:|
| Go source | 628.4 / 503.9 | 878.0 / 730.9 |
| CommonMark | 961.6 / 690.5 | 1230.3 / 943.8 |
| Inter font | 427.5 / 366.2 | 488.7 / 433.6 |
| OpenTelemetry JSON | 1123.9 / 771.6 | 1214.8 / 934.2 |
| Kubernetes JSON | 1991.8 / 1088.6 | 2433.8 / 1542.4 |
| Weather CSV | 914.8 / 669.5 | 1150.3 / 906.5 |

Every real-packet median improves in both modes. The smallest raw improvements
are 5.6% fresh and 5.7% reuse, both on Otel packets. This statement is limited
to these packets and measurements.

The broader existing synthetic diagnostic also improves: reused raw throughput
is 704.1 → 804.5 MB/s (+14.3%), and gzip is 526.7 → 623.8 MB/s (+18.4%). Its
separate tiny group is 1.6% slower raw and 5.0% faster gzip. These families have
been used in prior development and are not an unseen holdout.

## Small inputs, checksum rate and size

Tiny streams remain a separate latency regime. For the zlib-encoded 11-byte
`hello world` witness, median nanoseconds per call are:

| Context / frame | v5 | v6 | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| Fresh / raw | 44.4 | 48.5 | 129.4 | 1633.0 |
| Fresh / gzip | 65.3 | 66.2 | 149.8 | 1648.2 |
| Reuse / raw | 36.1 | 36.3 | 38.9 | 21.9 |
| Reuse / gzip | 54.6 | 60.4 | 49.2 | 24.6 |

The reused empty gzip witness is 35.9 → 43.0 ns. Restoring the compact path
removed the earlier large raw regression, but small gzip retains roughly 6–7 ns
of overhead here. Fresh hello raw is also about 4 ns slower. These costs are
not hidden by pooling tiny inputs with large files.

The selected CRC-only comparison is **2.51 → 4.03 GB/s (1.61×)** on the six
resident raw files, with five rotated serial sessions and 100 ms batches.
All 60 checksums match Python zlib. Input I/O is outside the timer. This is a
cache-resident checksum rate, not whole-gzip speedup or streaming memory
bandwidth. Native hardware checksum acceleration remains substantially ahead,
as established in the preceding audit.

Working lookup allocations fall by 5.5 KiB, but shared fixed tables and the
wider CRC tables increase linked size. The reuse diagnostic executable grows
from 498,608 to 550,448 bytes (+10.4%); the fresh executable grows from 498,304
to 550,224 bytes. These are complete Rust benchmark executables, not isolated
library sizes, and are not compared with native adapter sizes that exclude their
dylibs. Full peak-memory and cross-architecture evaluation remain outstanding.

## Selection and evidence

The first bounded-copy screen improved the real pool, and packed entries improved
it further. An alternative refill-state representation and grouped literals did
not improve their paired comparisons and were rejected. A rule that abandoned
batching after a short run was replaced with resumable fallback inside the
initialized region. Small-stream follow-ups retained the compact canonical
implementation and separated the large CRC loop from framing callers.

The initial frozen candidate had larger pooled gains but regressed tiny raw
decoding substantially. Its source snapshot and five receipts are retained as
`library-decode-v6-initial*`; they are not the selected implementation's results.
The selected source was frozen again before the comparisons in this report.
The [screening bundle](../scripts/reports/library-decode-v6-screening.json.gz)
retains development measurements, including unsuccessful variants; the reported
selected speedups come only from the final receipts below.

- [Fresh real](../scripts/reports/library-decode-v6-real.json.gz) and
  [reuse real](../scripts/reports/library-decode-v6-reuse-real.json.gz).
- [Fresh builtin](../scripts/reports/library-decode-v6.json.gz) and
  [reuse builtin](../scripts/reports/library-decode-v6-reuse.json.gz).
- [Broader synthetic](../scripts/reports/library-decode-v6-expanded.json.gz) and
  [complete selected source snapshot](../scripts/reports/library-decode-v6-core-sources.json.gz).

These final receipts contain 7,728 timed rows and 6,216 rejection checks, with
exact output checks after every timed batch. Source freezes include the new
untracked source module as well as tracked files; the benchmark controller now
includes both when recording identities. Twelve evidence tests check complete
pairs, matching modes, native identities, baseline bindings and source snapshots.

## Correctness and reproduction

New tests cover packed entries and canonical error cursors, allocation reuse and
stale-entry clearing, fixed-table construction, every short copy length/distance
boundary, batch boundaries, long-distance fallback resumption, dispatch boundaries,
suffixes and exact output limits. Existing tests compare block results, bit
positions and partial output with an independent canonical/bytewise reference.
CRC tests use an independent bitwise implementation and incremental updates.

The selected build passes `make test`: Rust tests, Lean axiom gates, 20,197
differential streams across three oracles with zero findings, and 1,654 framing
checks. All-feature workspace tests, Clippy with warnings denied, local Cargo
package verification and all twelve benchmark-evidence tests also pass.

Bounded fuzzing completed **20,057,895 runs** without a crash or disagreement:
3,842,575 reuse, 5,916,665 inflate, 8,772,834 dynamic-header, 1,287,093 differential
and 238,728 round-trip runs (46 seconds each). These are finite checks, not proof
of bug absence.

Validation logs and bounded fuzz results are retained in the
[validation receipt](../scripts/reports/library-decode-v6-validation.json.gz).

To reproduce, retain/rebuild the exact v5 baseline workers from their source
snapshot and receipt before building the current examples. The native builds and
real corpus are the pinned inputs described in the v5 report. Use new output
directories and run timers without concurrent validation workloads:

```sh
cargo build --locked --release -p deflate-core --example library_decode --example library_decode_reuse
python3 scripts/library_bench.py measure --reuse \
  --workers target/library-v5/workers-final \
  --baseline target/library-v6/baseline-reuse \
  --baseline-receipt scripts/reports/library-decode-v5-reuse-real.json.gz \
  --corpus-manifest target/library-v3/real-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v6/reproduce-reuse --sessions 5
make test
python3 scripts/test_library_bench.py
```

For fresh calls, omit `--reuse` and select `baseline-fresh` with the v5 fresh
receipt. Add `--candidate-freeze` when evaluating a frozen source/binary pair.
No formal Rust refinement proof is claimed; the Lean model is unchanged.
