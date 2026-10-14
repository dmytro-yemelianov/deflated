# x86-64 hardware-counter attribution v13 (diagnostic)

The v12 screen recommended counter attribution before writing more hot-loop
candidates. This iteration measures the existing decoders on x86-64 with Linux
`perf`. It covers user-mode cycles, instructions, branches, mispredicts and L1D
misses, plus precise sampling of where the core's cycles, load misses and
mispredicts land. **No production source changed.** The only additions are a
Linux measurement helper, an archive script and this report.

These results come from an Intel i7-8700 (Coffee Lake, x86-64). They do not
describe the Apple M5/arm64 gap measured in v8–v12. The pool is four pinned
real inputs on a shared, busy host. This is diagnostic evidence, not holdout
or release evidence.

## Setup

- **Host:** `raps-ci`, Linux 6.8.0, i7-8700 with 6 cores and 12 threads, the
  `powersave` governor (about 4.3 GHz observed) and microcode 0xfa. It is a
  shared CI host: about 20 GitHub runners, plus a Windows VM and another
  process that each use a full core continuously. Sampled load was uniform at
  about 19% busy on every logical CPU, because neither process is pinned. All
  timed and counted work was pinned to CPU 1, whose SMT sibling (CPU 7) could
  not be kept idle. Host settings were not changed.
- **Container:** one `rust:1.88-slim-bookworm` container with `linux-perf`
  6.1, clang 14.0.6, cmake/ninja and python3. It ran with only `--cap-add
  PERFMON --cap-add SYS_PTRACE --security-opt seccomp=unconfined`. CAP_PERFMON
  was enough with the host's `perf_event_paranoid=4`, so CAP_SYS_ADMIN and
  `--privileged` were not used.
- **Sources:** revision `31c39fc`. Rust 1.88.0 uses LLVM 20.1.5 and the
  default `x86-64` target, so it emits no BMI2. zlib-ng 2.3.3 and libdeflate
  1.26 were rebuilt from the locked source archives: their hashes match
  `new-methods-reference-sources.json`. They use the historical cmake options
  with clang 14 `-O3`. libdeflate selects `deflate_decompress_bmi2` at run time
  on this CPU, and zlib-ng also dispatches by CPU features.
- **Extra build:** `core-x86-64-v3` is the same core source built with
  `-C target-cpu=x86-64-v3` (BMI2/AVX2). It is a counter diagnostic, not a
  shipping option.

## Throughput (reused state and output, level 6, 5 sessions)

This uses the same controller and protocol as v11/v12: `library_bench.py
measure --reuse`, 3 encoders × 4 inputs × raw/gzip, 250 ms minimum samples,
rotated order and exact-output, truncation, suffix, size and CRC rejection
checks. There were 480 timed rows.

| Frame | Core (portable CRC) | Accelerated | zlib-ng 2.3.3 | libdeflate 1.26 |
|---|---:|---:|---:|---:|
| Raw | 394.0 MB/s | 408.5 MB/s | 487.4 MB/s | 689.4 MB/s |
| GZIP | 349.2 MB/s | 405.5 MB/s | 477.9 MB/s | 675.2 MB/s |

Per-session pooled raw MB/s ranged from 372 to 401 for the core and from 663 to
691 for libdeflate. On arm64 the core beat zlib-ng (v11/v12), but on this x86
host it trails zlib-ng by about 19% raw. libdeflate is 1.75× the core raw and
1.67× the accelerated adapter on gzip. The accelerated raw path runs the same
core code as the core worker. Its +3.7% is therefore binary layout or noise,
not an improvement.

## Counters per decoded byte

The helper runs `perf stat` with user-mode events in two groups of four, so
nothing was multiplexed (100% running in every row). Each decoder × packet ×
frame was run over a 0.5 s warm reuse loop, a one-decode cold run was
subtracted, and the result was divided by the loop's call count. The table
below is pooled over the 12 packets per frame, using the median of 3
repeats × 2 groups per packet.

| Frame | Decoder | Instr/B | Cycles/B | IPC | Branches/B | Br-miss/KiB | L1D repl./KiB |
|---|---|---:|---:|---:|---:|---:|---:|
| Raw | Core | 17.30 | 10.78 | 1.60 | 2.70 | 135 | 122 |
| Raw | Core x86-64-v3 | 15.76 | 9.67 | 1.63 | 2.70 | 122 | 121 |
| Raw | zlib-ng | 12.99 | 8.80 | 1.48 | 1.74 | 98 | 46 |
| Raw | libdeflate | 10.72 | 6.22 | 1.72 | 1.40 | 79 | 56 |
| GZIP | Core | 19.73 | 12.28 | 1.61 | 2.77 | 136 | 139 |
| GZIP | Accelerated | 17.75 | 10.60 | 1.68 | 2.72 | 123 | 138 |
| GZIP | zlib-ng | 13.53 | 8.96 | 1.51 | 1.75 | 99 | 62 |
| GZIP | libdeflate | 11.00 | 6.34 | 1.74 | 1.40 | 79 | 71 |

LLC misses are at most 0.03/KiB everywhere. On Intel, the generic
`L1-dcache-load-misses` event is `L1D.REPLACEMENT`, which also counts store
fills. True load misses were therefore measured separately with
`mem_load_retired.l1_miss`, over 1 s runs on the zlib-encoded raw packets:

| Packet | Core | Core v3 | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| `go`, L1 load misses/KiB | 102.0 | 122.6 | 17.1 | 33.0 |
| `inter`, L1 load misses/KiB | 51.9 | 53.6 | 9.2 | 16.1 |

The raw core and the accelerated adapter execute identical raw code, but
their mispredicts differ by 10% (135 vs 123 per KiB). Treat differences of that
size as layout or host noise. Repeated L1/L2 load-miss runs moved by roughly
8% and 2× respectively.

### Per token (zlib-encoded raw packets)

Token counts come from the `decode_shape` census: `go` has 41,048 tokens (34%
literals) and `inter` has 376,188 tokens (78% literals).

| Packet | Decoder | Instr/token | Cycles/token | Branches/token | Mispredicts/token |
|---|---|---:|---:|---:|---:|
| `go` | Core | 76.2 | 44.2 | 10.64 | 0.500 |
| `go` | Core v3 | 66.5 | 37.8 | 10.65 | 0.477 |
| `go` | zlib-ng | 59.5 | 34.3 | 7.59 | 0.395 |
| `go` | libdeflate | 51.2 | 26.0 | 6.60 | 0.358 |
| `inter` | Core | 44.2 | 28.1 | 6.99 | 0.366 |
| `inter` | Core v3 | 40.4 | 25.3 | 6.99 | 0.326 |
| `inter` | zlib-ng | 32.6 | 23.2 | 4.40 | 0.263 |
| `inter` | libdeflate | 27.0 | 16.2 | 3.52 | 0.211 |

## Where the core's events land

The core was sampled from a separate line-tables build: its `decode_tokens` has
1366 instructions, against 1364 in the timed binary. Sampled PCs were resolved
to inline chains with `addr2line -i` and assigned exclusively to the innermost
`block.rs`/`decode_table.rs` line range, as listed in the helper. Cycle
profiles hold about 20,000 samples each. The precise-event profiles hold
469–2158 samples, so their shares carry several points of sampling error.

| Category (share of core-binary samples) | Cycles, go | Cycles, inter | L1 load misses, go | L1 load misses, inter | Mispredicts, go | Mispredicts, inter |
|---|---:|---:|---:|---:|---:|---:|
| Match copy | 23.1% | 15.4% | 36.0% | 24.6% | 1.7% | 8.4% |
| Literal path | 16.5% | 21.2% | — | — | 69.7% | 61.5% |
| Match-value extraction | 15.3% | 11.0% | — | — | — | — |
| Table lookup | 11.9% | 15.2% | 62.0% | 71.3% | — | — |
| Bit refill | 7.7% | 9.4% | 0.1% | 1.3% | 23.6% | 26.8% |
| Length/distance decode | 6.9% | 3.5% | — | 0.1% | 0.4% | — |
| Literal/length dispatch | 5.2% | 7.1% | — | — | 0.2% | — |
| Unresolved lines, setup and other | 13.5% | 17.2% | 1.9% | 2.6% | 4.3% | 3.3% |

libc took 2.1–3.5% of all core samples. Those samples were not broken down by
symbol before the profiles were deleted. libdeflate spends 97–98% of its samples in
`deflate_decompress_bmi2` and 1.5–2.5% in `build_decode_table`.

Static code facts:
- **Baseline:** `decode_tokens` has 1364 instructions, nine cold
  slice-index/panic call sites outside the hot path and no BMI2 instructions.
- **x86-64-v3 build:** 1356 instructions, 26 of them BMI2 (`shrx`/`shlx`/`bzhi`).

A TopdownL1 run gave similar retiring and bad-speculation shares for all
decoders. The core was more frontend-bound on `inter` (29% vs 18% for
libdeflate). Those metrics multiplexed at 33% and use per-core `_ANY` events
contaminated by the busy SMT sibling, so they are supplementary only.

## What explains the gap to libdeflate

The cycle gap is 4.6 cycles/byte raw, which is 18.2 cycles/token on `go` and
11.9 on `inter`. In decreasing order:

1. **Instruction count.** It is the main term. The core retires 1.49× (`go`)
   to 1.64× (`inter`) libdeflate's instructions per token, and 1.6–2.0× its
   branches per token. Its IPC is 13% lower on `go`, 6% lower on `inter` and
   7% lower pooled. At the observed IPC, executing the extra instructions (25
   per token on `go`, 17 on `inter`) accounts for roughly 70–90% of the cycle
   gap. The lower IPC accounts for the rest, and items 2 and 3 contribute to
   it. BMI2 alone recovers 22–39% of this instruction gap on the
   two packets: −9.7 instr/token on `go`, −3.8 on `inter`, and −10% cycles/byte
   raw pooled. libdeflate is running its BMI2 variant here.
2. **Branch mispredicts.** The core has 1.4–1.7× libdeflate's mispredicts per
   token. At an assumed 15–20 cycle penalty, the extra 0.14–0.16
   mispredicts/token cost about 2.1–3.1 cycles, or 12–26% of the gap. This
   cost overlaps with item 1's accounting rather than adding to it. About a
   quarter of the core's sampled mispredicts are on the conditional refill
   branch, which libdeflate does not have: its fast-loop refill is branchless.
   Most of the rest are the data-dependent literal/match exits.
3. **L1D load misses.** The core has about 3× libdeflate's load misses per byte,
   and 62–71% of the sampled misses are at table lookups. The literal/length
   fast table is 4096 × 4 B = 16 KiB and the distance table 2 KiB, against
   libdeflate's 11-bit (8 KiB) and 8-bit roots. L2 still serves almost all
   misses. At about 12 cycles each, and assuming no overlap, they are an upper
   bound of 1 cycle/token on `inter` (≤8%) and 4.8 on `go` (≤26%). The real
   cost is lower where out-of-order execution overlaps them.

Bounds checks are not a measurable factor: the index-failure call sites are
cold, and no sampled cost lands on them. The portable gzip CRC costs 1.5
cycles/byte here, against 0.2 for the accelerated adapter.

## Candidate changes justified by these counters

1. **A smaller literal/length root table.** Try 10–11 bits instead of 12, with
   a second-level path for longer codes. That cuts the 16 KiB footprint behind
   most sampled L1 load misses. It also cuts per-block table construction,
   which matters for small dynamic streams. Measure L1 load misses per byte and
   cycles per token on `go`, where misses are largest.
2. **Branch-free refill in the fast loop.** Refill unconditionally on every
   token, as libdeflate does. Fold the "at least 8 readable input bytes"
   requirement into the batch loop condition so that the refill has no branch
   and its bounds check can be removed. This targets the ~25% of mispredicts
   sampled at the refill. Exact consumed-bit and error positions must be
   preserved and checked against the scalar decoder.
3. **A BMI2 path in `deflate-accel`.** Use runtime detection with
   `is_x86_feature_detected!` plus a `#[target_feature(enable = "bmi2")]`
   wrapper around an inlinable core entry point. The static x86-64-v3 build
   bounds the benefit at about −9% instructions and −10% cycles per raw byte.
   This needs a design decision: the core must stay portable and free of
   unsafe code, and the call into a target-feature function lives in the
   accelerator. The v3 build also showed more L1 load misses on `go`, so the
   gain must be confirmed by timing, not inferred.

Even with BMI2, the core still retires 1.47× libdeflate's instructions per
byte and 1.9× its branches per byte. The literal path, at 61–70% of
mispredicts and the largest per-token branch count, is the remaining
structural difference. It needs its own design rather than a local tweak.

## Evidence and reproduction

[`library-decode-v13-x86-counters.json.gz`](../scripts/reports/library-decode-v13-x86-counters.json.gz)
holds the full throughput report, all 720 counter rows, the cycle, load-miss
and mispredict attributions with their top PCs, the L1-split and TopdownL1
raw outputs, the `decode_tokens` disassembly, the native build receipts and
the environment. `python3 scripts/archive_v13_x86_counters.py` checks hash
consistency across those receipts and the current sources, and writes the
receipt once. The work directory on the host, including the corpus bodies and
binaries, was deleted after the receipts were copied. The image
`deflated-x86-perf:v13` (1.38 GB) was left on the host.

The counter sweep ran under an earlier revision of
`scripts/library_x86_counters.py` (`265ea043…`). That revision differed only in
the record and attribution code: the mmap regex fix, `--existing`, `--event`
and line-based `decode_table.rs` mapping. The record runs used the final
revision (`ba4429e2…`).

```sh
# inside the container, repository at 31c39fc, corpus as in target/library-v11/real-corpus.json
cargo build --locked --release -p deflate-core --example library_decode_reuse
cargo build --locked --release -p deflate-accel --example library_decode_reuse_accel
CARGO_TARGET_DIR=target/library-v13/lines CARGO_PROFILE_RELEASE_DEBUG=line-tables-only \
  cargo build --locked --release -p deflate-core --example library_decode_reuse
CARGO_TARGET_DIR=target/library-v13/v3 RUSTFLAGS="-C target-cpu=x86-64-v3" \
  cargo build --locked --release -p deflate-core --example library_decode_reuse
python3 scripts/library_x86_counters.py references --out target/library-v13/references \
  --source-lock scripts/reports/new-methods-reference-sources.json --codec zlib-ng --codec libdeflate
python3 scripts/library_bench.py build --references target/library-v13/references \
  --out target/library-v13/workers
taskset -c 1 python3 scripts/library_bench.py measure --workers target/library-v13/workers \
  --candidate target/release/examples/library_decode_reuse_accel \
  --baseline target/release/examples/library_decode_reuse --reuse \
  --out target/library-v13/measure --corpus-manifest target/library-v11/real-corpus.json \
  --levels 6 --sessions 5 --minimum-ns 250000000 --study library-decode-v13-x86-throughput
python3 scripts/library_x86_counters.py counters --workers target/library-v13/workers \
  --measure-run target/library-v13/measure --core target/release/examples/library_decode_reuse \
  --accel target/release/examples/library_decode_reuse_accel \
  --extra core-x86-64-v3=target/library-v13/v3/release/examples/library_decode_reuse \
  --cpu 1 --out target/library-v13/counters --minimum-ns 500000000 --repeats 3
python3 scripts/library_x86_counters.py record --binary target/library-v13/lines/release/examples/library_decode_reuse \
  --codec core --frame raw --packet target/library-v13/measure/go.zlib.raw --expected 244081 \
  --cpu 1 --out target/library-v13/record-core-go-raw   # also inter; --event mem_load_retired.l1_miss:upp
                                                        # and br_misp_retired.all_branches:upp at --frequency 2999
```

## What was and was not run

- **Run:** the controller's full validation (exact output and the rejection
  contracts for every decoder and packet), the 5-session throughput run, the
  counter sweep, six core profiles (cycles, L1 load misses and mispredicts, on
  `go` and `inter`), two libdeflate cycle profiles, the L1 load-miss split and
  TopdownL1.
- **Not run:**
  - zlib-ng profiles, gzip-frame profiles, and profiles of packets from the
    other two encoders.
  - Any arm64 counter measurement.
  - Rust tests and fuzzing: no Rust source changed since the passing
    2026-10-14 runs recorded in the [handover](handover.md).

The candidate changes above are hypotheses ranked by counter evidence. None has
been implemented or timed.
