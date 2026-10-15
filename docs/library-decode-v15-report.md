# Small-input latency v15: batched timer and fused code-length decoding

The [v10 profile](library-decode-v10-profile.md) found that tiny-input ns/call
included per-call clock reads and asked for batched timing before any further
small-input claim. This iteration adds that timer to every worker, measures
small raw and gzip inputs against zlib-ng and libdeflate, profiles the core on
those inputs and screens three candidates. **One candidate (C, fused
code-length decoding) was kept; A and B were rejected.**

This is diagnostic evidence on one Apple M5 development host (macOS, load
average 2–12 from unrelated work during the runs). Inputs are two tiny
witnesses plus prefixes of the four pinned real inputs; they are not holdout
data and this is not a release benchmark.

## Timer change (harness, not decoder)

The Rust example workers (`library_decode`, `library_decode_reuse` and their
`deflate-accel` counterparts) and the native `library_decode_worker.c` gain a
new mode each: `batched-warm` (fresh state and output per call, as `warm`) and
`context-batched` (reused state and output, as `context-warm`). An untimed
calibration doubles the batch size until one clock pair covers at least
100 µs (cap 2^20 calls). Timed batches then repeat until the minimum duration.
Every call keeps its size/consumption checks; the output bytes are compared
with the first decode after each batch, outside the timer. Workers print
`batch_calls` in this mode. `scripts/library_bench.py measure --batched`
selects these modes, records `"timer": "batched (>=100 us per clock pair)"`
and requires `batch_calls` in every sample. Existing modes and their output
are unchanged, so historical receipts stay reproducible with their frozen
binaries. Native workers were rebuilt into `target/library-v15/workers` from
the pinned v1 references (zlib-ng 2.3.3, libdeflate 1.26).

On the 11-byte gzip witness the reused core decoder measures 44 ns/call with
the old per-call timer and 33 ns/call batched. **Tiny-input ns/call from
earlier reports (v10 and before) used the per-call timer and are superseded;
they are not comparable with the numbers below.** Large-input results are
essentially unaffected (one call already exceeds 100 µs, so the batch is 1).

## Small-input corpus

`empty` (0 B), `hello` (11 B), 100 B / 1 KiB / 4 KiB / 16 KiB prefixes of
`go` and `vega-weather`, 1 KiB / 16 KiB prefixes of `inter`, and all of
`otel` (4134 B). Each is encoded by zlib, zlib-ng and libdeflate at level 6,
raw and gzip. Except `empty`/`hello` (stored or fixed blocks), every packet
is a single dynamic block. The controller's existing truncation, suffix,
wrong-size and corrupted-CRC rejection checks run on every packet and worker.

## Where small inputs spend time (baseline `1c0e00c`)

samply profiles of the batched reuse worker (line-table build, about 3000
samples each; profiler timing is not used for any speed figure):

| Share of samples | go-100 raw | inter-1k raw | otel raw | otel gzip |
|---|---:|---:|---:|---:|
| `peek_bits` (code-length symbols) | 19.8% | 27.1% | 19.4% | 14.0% |
| `read_dynamic_lengths` | 13.9% | 22.4% | 13.5% | 9.9% |
| `prepare` (counts, symbol order) | 21.8% | 13.6% | 11.8% | 9.2% |
| `build` + memset/memmove | 15.6% | 10.7% | 11.1% | 8.8% |
| bulk/tail token decoding | ~10% | ~13% | ~25% | ~5% |
| portable CRC (`update_slices`) | — | — | — | 24.6% |

For dynamic blocks under about 4 KiB the header (code-length decoding and
table construction) is the dominant cost. Header and setup structures are
reused across calls, so Decompressor setup, allocation and output growth do
not appear. `deflate-accel` already removes most of the small-gzip CRC share
(otel gzip 3676 → 2736 ns). At 11 bytes `crc32fast` and the portable CRC
measure the same here (hello gzip core 32 ns, accel 29–33 ns), so a length
threshold in `deflate-accel` is not justified by this data.

## Candidates

The screening rule: keep a candidate if the paired median ns/call over the
small cases improves by at least 3%, with no large-input regression above 2%
(v14 real-corpus reuse protocol on arm64, per-call timer, 5 sessions). An A/A
run of the identical baseline binary moved by −0.17% raw / +0.02% gzip
(paired median), with per-case medians within ±2.8%.

| Candidate | Small cases, paired median ns | Verdict |
|---|---|---|
| A. 8-byte load fast path in `BitReader::peek_bits` (same width check first) | −3.5% raw, −4.9% gzip | **rejected** |
| B. Wide counters, grouped checks in `prepare` | A+B: +4.5% raw (go-100 +23%) | **rejected** |
| C. Fused code-length decoding in `read_dynamic_lengths` | −5.9% raw, −5.0% gzip | **kept** |

**A** helped dynamic small cases (−5 to −12%) but cost about 1 ns on tiny raw
inputs and, in three separate large-input runs, made `go` gzip 2.1%, 3.3% and
(A alone, 7 sessions) 2.8% slower. That exceeds the 2% large-input limit.
C alone retains most of A+C's small-input gain (A+C: −7.4% raw / −8.8% gzip),
so A was dropped.

**B** counted every length, including zeros, into memory counters. Runs of
zero lengths form a serial store-to-load chain; go-100 and vega-100 became
about 20% slower. The original branch-on-zero loop is faster on these inputs.

**C** decodes each code-length symbol from one 64-bit lookahead word when at
least eight input bytes remain (at least 57 bits after the in-byte shift):
the 7-bit code-length table entry gives the symbol and code width, and the
repeat count's 2, 3 or 7 extra bits come from the same word. The bits are
consumed in the same order and amounts as before, and error checks (repeat
without a previous length, run past the total) keep their order. On a table
miss, or with fewer than eight bytes left, the existing checked reader is used.
It is about 20 lines in `crates/deflate-core/src/block.rs`; the core stays
`forbid(unsafe_code)`.

## Final results (C kept, 5 sessions, batched timer)

Paired median ns/call change against the `1c0e00c` baseline, small corpus:

| Decoder, context | Raw | Gzip |
|---|---:|---:|
| core, reused | −6.0% | −5.1% |
| core, fresh | −6.4% | −4.6% |
| deflate-accel, reused | −6.2% | −5.7% |
| deflate-accel, fresh | −6.2% | −5.7% |

Per case (core, reused): dynamic 100 B −12 to −13%, 1 KiB −9 to −17%,
4 KiB −4.5 to −11.5%, 16 KiB −1.5 to −3.4%; `empty` +0.1% / −0.4% and
`hello` +1.7% / +2.5% (within A/A per-case noise).

Reused state and output, ns/call (median over sessions, then encoders):

| Case | Frame | Core before | Core v15 | Accel v15 | zlib-ng | libdeflate |
|---|---|---:|---:|---:|---:|---:|
| empty | raw | 8 | 8 | 9 | 12 | 11 |
| hello | raw | 23 | 23 | 26 | 35 | 20 |
| go-100 | raw | 1195 | 1053 | 1055 | 1089 | 1279 |
| go-1k | raw | 2769 | 2478 | 2495 | 2807 | 2291 |
| inter-1k | raw | 4026 | 3365 | 3326 | 2995 | 2241 |
| otel | raw | 2777 | 2456 | 2452 | 2870 | 2368 |
| go-16k | raw | 14631 | 14323 | 14205 | 18692 | 12613 |
| empty | gzip | 15 | 15 | 16 | 21 | 13 |
| hello | gzip | 32 | 33 | 29 | 47 | 22 |
| go-100 | gzip | 1166 | 1019 | 1025 | 1086 | 1282 |
| go-1k | gzip | 2951 | 2662 | 2551 | 2900 | 2293 |
| inter-1k | gzip | 4235 | 3544 | 3415 | 3061 | 2229 |
| otel | gzip | 3676 | 3377 | 2736 | 3200 | 2408 |
| go-16k | gzip | 18472 | 18074 | 14994 | 20135 | 12773 |

Fresh calls, ns/call (new decoder and output per call):

| Case | Frame | Core v15 | Accel v15 | zlib-ng | libdeflate |
|---|---|---:|---:|---:|---:|
| empty | raw | 11 | 11 | 90 | 1514 |
| hello | gzip | 35 | 35 | 126 | 1545 |
| go-100 | raw | 1256 | 1284 | 1183 | 1408 |
| inter-1k | raw | 3570 | 3591 | 3095 | 2357 |
| otel | gzip | 3716 | 2998 | 3309 | 2554 |
| go-16k | gzip | 19165 | 15319 | 20123 | 12793 |

The full per-case tables (all 13 cases, both frames and contexts) are in the
receipt. In summary: with reused state, core v15 is faster than libdeflate at
100 B and on empty raw input, within 4% on `otel` raw, and 8–59% slower on the
other cases from 1 KiB upward. Against zlib-ng it is within ±3% at 100 B
(reused; 6–7% slower fresh), faster on most cases from 1 KiB up, and slower on
`inter-1k` and on `otel` gzip without the accelerator. libdeflate is fastest
on the 11-byte witness. For fresh calls libdeflate's decompressor allocation dominates tiny
inputs (about 1.5 µs) and zlib-ng's about 0.1 µs; the core allocates nothing
until a dynamic block needs tables. The remaining small-input gap to libdeflate
is mostly table construction (`prepare` and `build`).

**Large-input guard.** The v11 real corpus with the per-call timer, reused
state, 5 sessions: paired median −1.2% raw and −1.3% gzip; per file `go` +0.4%
raw / −1.2% gzip, `inter` −0.5% / −1.2%, `vega-weather` −1.0% / −0.9%, `otel`
−11.3% / −8.5%. No file regresses beyond the 2% limit.

## Validation run

On the final tree (C only): `cargo fmt --all --check`, `cargo clippy
--workspace --all-targets --all-features -- -D warnings`, `cargo test -p
deflate-core`, `cargo test -p deflate-accel`, `make test` (Rust tests, Lean
build and axiom gate, differential oracles 20197 streams / 0 findings,
framing 1654 checks) and `python3 scripts/test_library_bench.py` passed. The
native worker builds with `-Wall -Wextra -Werror`. Fuzzing was not run in this
iteration; `dynamic_header` and `inflate` are the relevant targets for C.

## Evidence and reproduction

The receipt
[`scripts/reports/library-decode-v15-small-latency.json.gz`](../scripts/reports/library-decode-v15-small-latency.json.gz)
(written by `scripts/archive_v15_small_latency.py`) records binary, packet and
source hashes, the small-corpus manifest, load readings, all three candidate
patches, the final source diff, profile attribution summaries, per-case
medians and paired results for every run, and full timed rows (0.1 ns) for the
baseline, A/A, final and guard runs.

```sh
# arm64, repository at 1c0e00c plus the v15 worker changes
python3 scripts/library_bench.py build --references target/library-v1/references \
  --out target/library-v15/workers
cargo build --locked --release -p deflate-core --example library_decode_reuse --example library_decode
cargo build --locked --release -p deflate-accel --examples
python3 scripts/library_bench.py measure --workers target/library-v15/workers \
  --corpus-manifest target/library-v15/small-corpus.json --levels 6 --batched \
  --minimum-ns 50000000 --sessions 5 --reuse \
  --candidate target/release/examples/library_decode_reuse \
  --baseline <baseline library_decode_reuse> --out <new dir>
# fresh calls: drop --reuse and use library_decode; accel: *_accel workers.
# large-input guard (per-call timer):
python3 scripts/library_bench.py measure --workers target/library-v5/workers-final --reuse \
  --candidate <candidate> --baseline <baseline> --out <new dir> \
  --corpus-manifest target/library-v11/real-corpus.json --levels 6 --sessions 5 \
  --minimum-ns 250000000
python3 scripts/archive_v15_small_latency.py
```

The small corpus manifest is generated from the pinned real inputs under
`target/library-v10/selected/final-reuse-real/`; its case hashes are in the
receipt.

## Next

Table construction is now the largest small-input cost: `prepare` and `build`
(including the root-table doubling copies) for the 11-bit literal/length
table. A lower-cost build for small blocks (for example, building only the
populated prefix or skipping the doubling for short codes) and an x86-64 run of
this small-input protocol are the next candidates. Fuzz `dynamic_header` and
`inflate` against the C change before the next release-evaluation step.
