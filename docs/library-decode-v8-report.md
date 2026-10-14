# Library decode v8: transfer the native loop structure

V8 combines three related native-loop ideas: total-bit action entries, grouped
literals and byte-cursor refill. On the six-file arm64 development pool it
improves raw throughput by **19–22% over v7** and gzip by **16–17%**. Raw
DEFLATE is now **about 7% faster than pinned zlib-ng 2.3.3** in both fresh and
reused-state comparisons. Libdeflate 1.26 remains 43–45% faster raw, and both
native libraries remain faster for gzip. This is a local development result,
not an independent or cross-architecture release qualification.

## What the native code explained

The earlier [source/AST audit](native-decode-audit.md) correctly identified the
relevant native paths, but transferring individual copies and preloads did not
transfer the whole loop structure. The remaining differences were concrete:

| Operation | V7 | Native source and accepted v8 adaptation |
|---|---|---|
| Find the distance entry | Extract code bits and extra-bit count, add them, then shift/index | Store total consumed bits in the action; the next table lookup no longer waits for that addition |
| Classify the action | Extract symbol and compare literal, EOB and length ranges | Explicit literal/EOB flags; zero retains checked fallback for misses/reserved symbols |
| Literal runs | Return to loop/refill/output checks after each byte | Handle up to three literals in one checked iteration |
| Bit position | Maintain both a bit position and available-bit count per token; refill from the current position | Track a byte cursor and available bits, append input with an OR refill, derive the logical position only at handoff |

Pinned libdeflate source documents total-bit length entries in
`lib/deflate_decompress.c` and the grouped loop in `lib/decompress_template.h`.
Its branchless refill preserves a byte-pointer/bit-count invariant. The Rust
adaptation uses checked input slices and the existing initialized output batch;
it does not assume padded input or writable spare capacity.

The action remains 32 bits:
`[value:16 | end:1 | literal:1 | index:5 | code bits:4 | total bits:5]`.
The index preserves exact symbol decoding for the checked path. Length/distance
values are extracted using total bits and code bits; root widths and table
allocations remain 12/9/7 bits and 18.5 KiB. The public `HuffmanTable` is unchanged.

Refill preserves `logical_position = next_byte * 8 - available`, appending a
real eight-byte load and retaining 56–63 counted bits. High bits overlapping
the next load come from those same input bytes, so OR preserves their values.
Only completed tokens affect the position handed back to `BitReader`. The
three-literal path has enough real bits for every code and uses one three-byte
output slice. A miss, invalid distance, input boundary or output boundary returns
to the existing checked decoder with the exact cursor and partial output.

Changes are in [block.rs](../crates/deflate-core/src/block.rs) and
[decode_table.rs](../crates/deflate-core/src/decode_table.rs). The API, compact
fixed-block path, CRC and allocation strategy are unchanged. The core remains
safe `no_std` + `alloc` Rust with zero runtime dependencies.

## What assembly showed, and what was rejected

V7's ARM64 assembly contains six bounds-check branches before the first two
word copies, plus stack traffic around the match path. Those checks are present
despite the outer 264-byte guard: their elimination is not obvious to LLVM from
the original slice/index expressions.

An experiment reduced the copy checks to two by using a relative bounded slice.
LLVM also fully unrolled the continuation, and the real-pool screen became
about 8% slower raw. Forcing a separate non-inlined batch function was also
about 9% slower. Both were rejected. Static check counts alone do not establish
the cause of the throughput gap; the accepted code still has copy checks and
some stack spills. No PMU stall attribution is claimed.

The cumulative screens against v7 were:

| Candidate | Raw v7-relative throughput |
|---|---:|
| Relative copy slice, fully unrolled continuation | 0.921× — rejected |
| Separate batch function | 0.913× — rejected |
| Total-bit actions and flags | 1.014× |
| Actions plus grouped literals | 1.108× |
| Actions, grouped literals and byte-cursor refill | 1.210× |

These runs are exploratory and not additive causal measurements. The final
candidate below was frozen separately after the new tests and invariant comments.
The evidence archive retains each source overlay, matching worker hashes and
assembly listings, including the rejected alternatives.

## Final paired measurements

The same six pinned files, three encoders and levels 1/6/9 yield 108 raw/gzip
packets. Five rotated serial sessions use at least 20 ms per batch, exact output
validation, and matching fresh/reuse modes for every decoder. Native gzip calls
include their checksums. Final timers run without concurrent builds, tests,
profilers or fuzzing. Throughput is pooled bytes divided by summed per-packet
median times; it is not an average of file throughputs.

| Mode | Frame | v7 MB/s | v8 MB/s | zlib-ng | libdeflate | v8/v7 |
|---|---|---:|---:|---:|---:|---:|
| Fresh | Raw | 797.1 | 951.3 | 891.9 | 1382.3 | 1.193× |
| Fresh | Gzip | 622.2 | 726.8 | 800.1 | 1350.3 | 1.168× |
| Reuse | Raw | 906.9 | 1102.0 | 1030.1 | 1573.5 | 1.215× |
| Reuse | Gzip | 738.1 | 856.6 | 935.5 | 1545.2 | 1.161× |

All ten real-file raw sessions exceed zlib-ng when pooling that session's times:
3.7–8.4% fresh and 6.1–9.1% reuse. Five of six file-level raw pools beat zlib-ng
in both modes; Otel remains slower. This supports a scoped raw-decode win on
these inputs, not an all-file or all-packet claim.

| File | Reuse v8 raw MB/s | zlib-ng | libdeflate | v8/v7 |
|---|---:|---:|---:|---:|
| CommonMark | 1898.9 | 1557.1 | 2463.3 | 1.374× |
| Go | 1418.9 | 1088.5 | 1777.5 | 1.434× |
| Inter | 603.2 | 588.7 | 881.1 | 1.161× |
| Kubernetes | 3644.4 | 3346.6 | 5398.3 | 1.299× |
| Otel | 1418.1 | 1443.5 | 1765.5 | 1.155× |
| Weather CSV | 1759.8 | 1392.2 | 2100.1 | 1.411× |

Every reused real-packet median improves against v7: at least 11.8% raw and
7.7% gzip. Fresh raw packet medians all improve, but fresh Otel/zlib-6 gzip is
4.2% slower. Session ratios against v7 are 1.157–1.211 fresh raw and
1.203–1.234 reuse raw. Fresh gzip is noisier (0.942–1.226); reused gzip spans
1.149–1.179. Absolute rates vary materially between runs, so the comparisons
use paired workers and retain all rows.

The existing broader synthetic pool improves 869.0 → 1103.4 MB/s raw (+27%)
and 690.1 → 839.9 MB/s gzip (+22%). Its separate tiny group regresses 3.0% raw
and 2.7% gzip. These are development families, not an unseen holdout.

## Tiny inputs, memory and remaining gap

The zlib-encoded eleven-byte `hello world` witness, median ns/call:

| Mode / frame | v7 | v8 | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| Fresh / raw | 43.6 | 48.2 | 127.4 | 1612.0 |
| Fresh / gzip | 66.1 | 69.7 | 146.7 | 1671.9 |
| Reuse / raw | 39.1 | 39.0 | 40.2 | 23.3 |
| Reuse / gzip | 70.5 | 64.5 | 51.6 | 26.8 |

Fresh tiny raw regresses about 4.6 ns despite retaining the compact path; the
new bulk loop does not provide a tiny-input speedup. Reused empty gzip is
46.2 → 46.9 ns. The earlier small-message work remains unfinished.

Diagnostic executable sizes remain 550,224 bytes fresh and 550,448 bytes reuse.
Lookup allocation and initialized batch bounds are unchanged. These executable
sizes are not isolated library sizes, and no new peak-RSS measurement is claimed.

Libdeflate still has a 1.43–1.45× raw throughput advantage. V8 has not eliminated
all copy checks or stack traffic, and its fallback/table design still differs
from native subtables. Gzip retains a separate portable CRC cost; this iteration
does not add the native hardware checksum instructions. A precise causal split
of the remaining gap is not established by static assembly or sample counts.

## Validation and reproduction

New tests exhaust every extra length/distance value across code widths 1–15,
including unrelated code/following bits, and check reserved entries. Literal-run
tests compare results, partial output and exact scalar positions for all initial
bit alignments, every truncation of short runs, all three group-ending positions,
the 63/64/65-byte dispatch region and output limits. Existing tests cover every
match length, overlapping history, maximum distances, long-code fallback and
batch boundaries. The [verification boundary](verification-boundary.md) records
the new refill invariant without claiming a Rust refinement proof.

The selected source passes `make test` (Lean gates, 20,197 differential streams
against three oracles with zero findings, and 1,654 framing checks), all-feature
workspace tests, Clippy with warnings denied, formatting, Cargo package
verification and fourteen benchmark-evidence tests. Five bounded fuzz targets
completed 13,222,404 executions without a crash or disagreement (31 seconds
each); counts and full logs are retained in the validation receipt.

The five final receipts contain 7,728 timed rows and 6,216 rejection checks.
The complete 28-file source snapshot matches every frozen source hash. Prior
v1–v7 evidence and reference builds are preserved.

- [Fresh real](../scripts/reports/library-decode-v8-real.json.gz) and
  [reuse real](../scripts/reports/library-decode-v8-reuse-real.json.gz).
- [Fresh builtin](../scripts/reports/library-decode-v8.json.gz),
  [reuse builtin](../scripts/reports/library-decode-v8-reuse.json.gz) and
  [broader synthetic](../scripts/reports/library-decode-v8-expanded.json.gz).
- [Source snapshot](../scripts/reports/library-decode-v8-core-sources.json.gz),
  [source/assembly/screens](../scripts/reports/library-decode-v8-screening.json.gz),
  and [validation receipt](../scripts/reports/library-decode-v8-validation.json.gz).

Retain/reconstruct the v7 baseline workers from their archived source and hashes
before building this candidate. Use a fresh output directory:

```sh
cargo build --locked --release -p deflate-core --example library_decode --example library_decode_reuse
python3 scripts/library_bench.py measure --reuse \
  --workers target/library-v5/workers-final \
  --baseline target/library-v8/baseline-reuse \
  --baseline-receipt scripts/reports/library-decode-v7-reuse-real.json.gz \
  --corpus-manifest target/library-v3/real-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v8/reproduce-reuse --sessions 5
make test
python3 scripts/test_library_bench.py
```

For fresh mode, omit `--reuse` and select the fresh baseline and v7 fresh receipt.
Independent application inputs, x86-64, peak memory and the remaining native
gaps must still be evaluated before declaring the library broadly competitive.
