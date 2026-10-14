# Raw hot-loop screen v12 (negative result)

The v10 profile attributed Go raw decode samples mostly to packed-table lookup
(20.5%), match copying (18.2%) and match-value extraction (11.5%). This
iteration inspected the release AArch64 code of `decode_tokens`, screened three
safe source changes aimed at that loop, and **kept none**. Production sources
are unchanged from the v11 state; the rebuilt core worker hash equals the frozen
baseline (`e12ba574…cdd86`).

## What the compiled loop shows

`decode_tokens` (1183 instructions, Rust 1.88.0, LLVM 20.1.5, Apple M5) already
has the libdeflate-style shape. The literal and distance lookups are masked
fixed-size array loads without bounds-check branches. A match costs two region
checks, five unconditional 8-byte load/store pairs, and the next literal lookup
issued before the copy. Packed-entry extraction is the same mask/shift sequence
libdeflate uses. Two inefficiencies were visible:

- Register pressure. The distance-table pointer and four precomputed store
  bases (`out+8` … `out+32`) are reloaded from the stack on every match, which
  adds five loads per match.
- The `while copied < len` tail is fully unrolled into 32 compare/copy steps
  inline.

## Candidates

Each candidate passed `cargo test -p deflate-core`. It was then screened
against the frozen baseline with the existing paired controller on the v11
corpus: four pinned real inputs, three encoders, level 6, raw and gzip,
reused state and output, a 250 ms minimum per sample. The host was busy
(load average 4–8 from unrelated processes). An A/A run timed the baseline
binary against itself to calibrate noise.

| Screen | Sessions | Pooled raw Δ | Median paired raw Δ | Worst case median | Verdict |
|---|---:|---:|---:|---:|---|
| A/A (baseline vs itself) | 3 | −0.52% | −0.19% | otel −2.6% | noise floor |
| A: out-of-line long-copy tail | 3 | +0.63% | +0.15% | go −4.0% | rejected |
| B: one disjoint 40-byte copy when distance ≥ 40 | 5 | +12.34% | −0.10% | otel −0.7% | rejected |
| C: tables resolved to `&[u32; N]` once per batch | — | — | — | — | rejected, identical code |

- **A** reduced stack references in `decode_tokens` from 91 to 58, but the store
  bases were still spilled. It showed no paired improvement and regressed Go
  raw by 4.0%.
- **B** produced a two-q-register plus one-word copy for distance ≥ 40, but it
  also reloaded the literal-table pointer after each copy. The +12.3% pooled
  figure comes from a few outlier pairs on `inter` (per-pair geomean +9.2%,
  median −0.1%). The paired medians show no effect.
- **C** compiled to instructions identical to the baseline after normalizing
  addresses: LLVM had already hoisted the `Lookup` enum resolution. It was not
  timed.

The A/A run shows that on this host, pooled MB/s moves by several percent
between identical binaries, and per-pair outliers reach −28%. Pooled
throughput alone is therefore not a valid acceptance metric here. Future
screens should also require the median paired ratio to move clearly beyond
the A/A range (about ±2.5% per case). The controller's own console summary
aggregates differently from the analyzer used here. This report and its receipt
use the archived analyzer for every number.

## Reference comparison (A/A screen, baseline binary)

| Frame | Core (v11 state) | zlib-ng 2.3.3 | libdeflate 1.26 |
|---|---:|---:|---:|
| Raw | 722.9 MB/s | 660.0 MB/s | 1002.7 MB/s |
| GZIP | 595.0 MB/s | 628.3 MB/s | 1009.5 MB/s |

The core's own GZIP path uses the portable CRC; the accelerated adapter is not
in this run. These numbers come from a noisy diagnostic pool, not holdout or
release evidence, and they are not comparable in absolute terms with the v11
table.

## Conclusion and next direction

Small source-level reshaping of the match path does not move this loop. LLVM
either already performs the change (C) or trades one spill for another (A, B).
The remaining libdeflate gap is not explained by bounds checks or table
indirection. The next useful step is hardware-counter attribution of the raw
loop. On macOS that means Instruments CPU Counters or `kperf`: cycles,
instructions, branch mispredicts and L1D misses for the core and libdeflate
on Go/Inter. This would show whether the gap comes from instruction count,
mispredicts on the literal/match split, or a dependency chain, before more
candidates are written. Measurement should run on a quiet host or with more
sessions, gated on paired medians.

## Evidence and reproduction

[`library-decode-v12-hot-loop.json.gz`](../scripts/reports/library-decode-v12-hot-loop.json.gz)
contains the three timed reports with all rows, the candidate patches, the
binary hashes, the paired summaries and the instruction-identity result for C.
It is produced once by `python3 scripts/archive_v12_hot_loop.py`, which checks
that every timed binary hash and the candidate C instruction identity still
hold. The reconstructed patches rebuild byte-identical candidate binaries. Each
report's `source_sha256` field records the working tree at measurement time.
For the A/A screen that tree was candidate A's, but both timed binaries were the
frozen baseline, bound by hash.

```sh
CARGO_TARGET_DIR=target/library-v12/baseline cargo build --locked --release \
  -p deflate-core --example library_decode_reuse
cp target/library-v12/baseline/release/examples/library_decode_reuse \
  target/library-v12/baseline-library_decode_reuse
# apply target/library-v12/patches/candidate-<x>.diff, then build into
# target/library-v12/cand-<x> and copy to cand-<x>-library_decode_reuse
python3 scripts/library_bench.py measure --workers target/library-v5/workers-final \
  --candidate target/library-v12/cand-<x>-library_decode_reuse \
  --baseline target/library-v12/baseline-library_decode_reuse \
  --reuse --out target/library-v12/screen-<x> \
  --corpus-manifest target/library-v11/real-corpus.json \
  --levels 6 --sessions 5 --minimum-ns 250000000 --study v12-screen-<x>
python3 scripts/archive_v12_hot_loop.py
```

## Validation

No production source changed, and the rebuilt worker hash matches the baseline.
After the final revert, `cargo fmt --all --check`, `cargo clippy --workspace
--all-targets --all-features -- -D warnings` and `cargo test --workspace` pass.
`make test` and the ten bounded fuzz targets passed earlier on 2026-10-14 on
these same sources (see the [handover](handover.md)). They were not rerun
because nothing they cover changed.
