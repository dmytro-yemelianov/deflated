# Decode candidates v14: subtable root, branch-free refill, BMI2 dispatch

The [v13 x86-64 counters](library-decode-v13-x86-counters.md) attributed the
gap to libdeflate mainly to instructions per token. Smaller shares came from
mispredicts at the conditional refill and literal exits, and from L1D misses
at the 16 KiB literal/length table. They proposed three candidates. This
iteration implements all three and screens each separately against a frozen
baseline (`5805003`) on arm64 and x86-64, using paired medians. It then
measures the combination. **All three were kept.**

This is diagnostic evidence from four pinned real inputs
(`go`, `inter`, `otel`, `vega-weather`), three encoder lineages, level 6 and
reused state and output. The inputs are not holdout data, the hosts were
shared and loaded, and this is not a release benchmark.

## What changed

1. **Literal/length subtables (core).** The literal/length root shrinks from
   12 bits (4096 entries, 16 KiB) to 11 bits (2048 entries, 8 KiB). Codes of
   12–15 bits use a second-level subtable. A root entry for a long code is an
   `END` action whose index field is 31, which no end-of-block action carries.
   The hot loop checks for it only after `END`, so literal and match dispatch
   are unchanged. Previously, codes longer than 12 bits left the bulk loop for
   the canonical decoder. Now they stay in the batch. `decode_symbol` keeps
   falling back to the canonical decoder for subtable codes, which preserves
   its exact cursor and error behaviour. Distance and code-length tables are
   unchanged.
2. **Branch-free refill (core).** `decode_batch` hoists the input bound into
   the loop condition and refills unconditionally on every iteration. It still
   loads eight bytes, ORs them above `available`, advances whole bytes and
   keeps 56–63 bits. The first word claims only seven bytes, so `available`
   stays below 64 and the shift is always in range. A `const` assertion checks
   that one refill covers the largest token, `L::MAX_BITS + 5 + D::BITS + 13`,
   and the largest literal group, `L::MAX_BITS + 2 * L::BITS`, while leaving
   `L::BITS` valid bits for the preloaded lookup. The scalar paths near the
   end of input are unchanged.
3. **BMI2 dispatch (`deflate-accel` only).** On x86-64,
   `is_x86_feature_detected!` checks for BMI1, BMI2, LZCNT and POPCNT and then
   selects `#[target_feature]` wrappers around the unchanged core decoder. To
   compile the hot loop inside the wrappers, the core marks the decode chain
   `#[inline(always)]`:
   - `Decompressor::inflate_into` and `gunzip_into_with_crc32`
   - `decode_reusing`, `decode_tokens` and `decode_batch`
   - the gzip member loop

   The gzip path now passes `DynamicTables` directly rather than a closure, and
   the fixed and dynamic paths share one `decode_tokens` call site, so only one
   copy of the bulk loop is inlined per entry. The accelerator has two `unsafe`
   blocks (the guarded calls) and denies `unsafe_op_in_unsafe_fn`. The core
   keeps `forbid(unsafe_code)`. The boundary is documented in
   [`crates/deflate-accel/README.md`](../crates/deflate-accel/README.md). On
   other architectures the crate compiles to the plain path.

Plain `#[inline]` did not work. The x86 wrapper then contained no
`shrx`/`bzhi`: `decode_tokens` stayed out of line and was compiled without the
features. With the forced chain, both wrappers (raw and gzip) contain the
whole bulk loop, with 22 BMI2 shifts and no legacy `%cl` shifts each
(objdump, `x86_64-apple-darwin` cross build). In the Linux container build,
the accelerator binary has 44 (candidate 3) or 48 (combined) `shrx`/`bzhi`,
and the baseline has none.

## Screening rule and noise

A candidate is kept if its raw paired median improves by at least 2% on one
architecture, with no median regression above 3% on the other and no file
regressing by more than 5%. Paired ratios are baseline time divided by
candidate time, for the same packet, encoder and session. The paired median
pools all files; per-file values are medians over encoders and sessions. The
A/A runs (baseline against itself) give the noise floor:

| A/A | Raw median | Gzip median | Worst file median |
|---|---:|---:|---:|
| arm64 | +0.33% | −0.15% | +1.0% / −1.2% |
| x86-64 | −0.11% | +0.31% | −0.9% / −1.8% |

## Per-candidate results (3 sessions each)

| Candidate | arm64 raw | arm64 gzip | x86 raw | x86 gzip | Verdict |
|---|---:|---:|---:|---:|---|
| 1: 11-bit root + subtables | +1.09% | +1.02% | **+2.51%** | +4.08% | kept |
| 1b: 10-bit root + subtables | +1.28% | +0.67% | — | — | not chosen |
| 2: branch-free refill | **+7.16%** | +5.13% | **+14.07%** | +11.94% | kept |
| 3: core inlining (core worker) | −0.08% | +0.06% | +3.35% | +0.59% | kept |
| 3: BMI2 dispatch (accel worker) | −0.63% | +0.11% | **+5.56%** | +7.99% | kept |

The per-file evidence behind each verdict:

- **Candidate 1, x86.** Per-file raw medians are go +0.5%, inter +10.4%,
  otel +4.7% and vega −0.4%. The gain lands where dynamic tables are large.
  - On arm64, the 11-bit root ranges from go −0.8% to otel +3.0%.
  - On arm64, the 10-bit variant had go −1.9% and inter −1.1%, so the 11-bit
    root (libdeflate's width) was the one kept and sent to x86.
- **Candidate 2.** It is positive on every file on both architectures:
  - arm64: +0.5% to +18.4%
  - x86: +4.4% to +21.6%
- **Candidate 3, core change alone.** The worst file medians are arm64 inter
  −3.5% and x86 vega −4.0%, both within the 5% per-file limit.
- **Candidate 3, BMI2 accel.** All x86 files are positive, from +3.7% to
  +8.8%. On arm64 it is unchanged within noise, from −2.3% to 0.0%, because
  arm64 uses the plain path.

## Combined results

| Combination | arm64 raw | arm64 gzip | x86 raw | x86 gzip |
|---|---:|---:|---:|---:|
| 1+2, core | +8.46% | +7.61% | +18.59% | +13.64% |
| 1+2+3, core | +7.74% | +5.00% | — | — |
| 1+2+3, accel | +7.91% | +6.35% | +22.93% | +23.88% |
| **Final, core (5 sessions)** | **+6.99%** | **+5.02%** | **+19.20%** | **+8.06%** |
| **Final, accel (5 sessions)** | **+8.71%** | **+7.08%** | **+23.17%** | **+24.47%** |

Every per-file median in the final runs is positive on both architectures:

- arm64 raw: +4.6% to +14.9%
- x86 raw: +3.7% to +30.8%

Pooled throughput in the final runs, against the pinned references, in MB/s:

| Host | Frame | v13 baseline | v14 | zlib-ng 2.3.3 | libdeflate 1.26 |
|---|---|---:|---:|---:|---:|
| arm64 (core) | raw | 747.0 | **855.5** | 690.6 | 1048.9 |
| arm64 (core) | gzip | 626.9 | **684.0** | 653.3 | 1038.9 |
| x86-64 (core) | raw | 390.1 | **484.0** | 480.9 | 684.2 |
| x86-64 (core) | gzip | 345.9 | 388.2 | 474.1 | 664.4 |
| x86-64 (accel) | raw | 404.3 | **502.9** | 485.5 | 684.5 |
| x86-64 (accel) | gzip | 402.8 | **492.9** | 475.3 | 670.7 |

The arm64 accelerator's final run is omitted from this table. All four
decoders' pooled numbers dropped in that run (zlib-ng was 477.5 MB/s raw
versus 690.6 in the core run), and its minimum paired ratios fell to −55%. Its
paired medians above remain the comparison. On x86-64, the portable core now
matches zlib-ng on raw input, and the accelerator exceeds it on both raw and
gzip. libdeflate remains 36–41% faster than the accelerator on x86-64 and
about 23% faster than the core on arm64. Gzip with the portable CRC still
trails zlib-ng on x86-64.

## x86-64 counters (user mode, per decoded byte, pooled)

| Raw decoder | instr/B | cycles/B | IPC | br-miss/KiB | L1D miss/KiB |
|---|---:|---:|---:|---:|---:|
| core v13 | 17.30 | 10.80 | 1.60 | 135.7 | 121.6 |
| + cand1 (subtables) | 17.56 | 9.95 | 1.77 | 121.9 | **77.6** |
| + cand2 (refill) | 17.09 | 8.98 | 1.90 | **86.6** | 115.6 |
| + cand3 (core inlining) | 18.38 | 10.25 | 1.79 | 122.6 | 121.3 |
| accel v13 | 17.30 | 10.37 | 1.67 | 122.3 | 119.7 |
| accel + cand3 (BMI2) | **16.00** | 10.03 | 1.60 | 123.3 | 122.0 |
| core 1+2 | 17.25 | 8.84 | 1.95 | 86.1 | 76.1 |
| **accel 1+2+3** | **15.97** | **8.35** | **1.91** | **86.4** | **75.8** |
| zlib-ng | 12.99 | 8.77 | 1.48 | 98.6 | 45.5 |
| libdeflate | 10.72 | 6.20 | 1.73 | 79.0 | 54.7 |

The counters match the mechanisms each candidate targeted:

- **Subtables** cut L1D load misses per byte by 36% while slightly increasing
  instructions.
- **Branch-free refill** cut mispredicts per byte by 36%. That is more than the
  quarter v13 attributed directly to the refill branch, so it probably also
  removes mispredicts that v13 counted at literal exits. It raised IPC from
  1.60 to 1.90.
- **BMI2** cut instructions per byte by 7.5%.

Combined, cycles per raw byte fell 23% (10.80 to 8.35), below zlib-ng's 8.77.
The remaining gap to libdeflate is still mostly instruction count: 1.49× its
instructions per byte at similar IPC. Gzip rows show the same pattern; see the
receipt. The counter method, CPU pinning and caveats are the same as in v13.

## Costs and limits

- **Code size.** Forced inlining duplicates the bulk loop into each public
  decode entry point, and the accelerator also carries the BMI2 copy. On
  arm64, the core benchmark worker's `__text` grows from 271,160 to 284,696
  bytes (+5.0%), and the accelerator worker's from 273,808 to 282,080 bytes
  (+3.0%). The x86-64 linked-size delta was not measured.
- **Behaviour.** Errors, limits, cursors and output semantics are unchanged.
  The free `gunzip_into` now reuses one `DynamicTables` across the members of a
  single call. Every dynamic header rebuilds all tables, so no state crosses
  members.
- **Not covered here.**
  - Small-gzip latency, the batched-timer correction from the v10 profile,
    and allocator or peak-memory measurements.
  - Holdout inputs.
  - Other x86 microarchitectures. Only one Coffee Lake host was measured.
- **Hosts.**
  - arm64 load averages ranged from 2.4 to 10 during the screens. Builds ran
    concurrently with the first candidate 2 screen, and its gzip pooled numbers
    are distorted. The screen gates use paired medians, not pooled MB/s.
  - The x86-64 host was the shared `raps-ci` runner described in v13, about
    15% busy on every logical CPU. Work was pinned to CPU 1.

## Validation run

- **Main tree with the kept set:**
  - `cargo fmt --all --check`
  - `cargo clippy --workspace --all-targets --all-features -- -D warnings`,
    and the same with default features
  - Clippy for `x86_64-unknown-linux-gnu` on `deflate-core` and
    `deflate-accel`
  - `cargo build -p deflate-core --target riscv32imac-unknown-none-elf`, a
    `no_std` build (CI has no no_std job)
  - `cargo test -p deflate-accel`
  - `make test`: Rust, Lean, the axiom gate, and the differential and framing
    oracles
  - all ten 60-second `make fuzz` targets, with no findings
- **On the x86-64 host,** whose CPU reports `bmi2`, `cargo test -p
  deflate-core -p deflate-accel` passed in debug and release on the exact
  final sources. This is the only run that exercised the BMI2 dispatch path
  under the equivalence tests. The fuzz targets ran on arm64 only.
- **New tests:**
  - every 15-bit prefix of random complete 286-symbol codes (up to 15 bits)
    resolves through the root and subtable to the canonical action, with high
    bits ignored
  - a block-level comparison of `decode_tokens` with `decode_huff_block` on
    streams biased towards 14–15-bit codes, across truncations and limits
  - a rebuild test that covers retained subtable storage

## Evidence and reproduction

The receipt is
[`scripts/reports/library-decode-v14-decode-candidates.json.gz`](../scripts/reports/library-decode-v14-decode-candidates.json.gz),
written by [`scripts/archive_v14_decode_candidates.py`](../scripts/archive_v14_decode_candidates.py).
It contains:

- every arm64 screen report, with timed-binary hashes validated at archive
  time
- every x86-64 measurement report, plus the container binary hashes, the
  toolchain and the BMI2 instruction counts
- the x86-64 counter summary and rows
- each candidate's patch, and the final source diff against `5805003`

On arm64, each screen's `source_sha256` records the working tree at the time,
which was `HEAD` for every run except `final-*`. Candidates were built from
separate worktrees and bound by binary hash. The x86-64 candidates were built
in the container from per-candidate source overlays. The final x86-64 timings
used the combined overlay, which differs from the final tree only by
`cargo fmt` line wrapping.

```sh
# arm64, repository at 5805003 plus a candidate patch, pinned workers from v5
CARGO_TARGET_DIR=target/library-v14/<name> cargo build --locked --release \
  -p deflate-core --example library_decode_reuse -p deflate-accel --example library_decode_reuse_accel
python3 scripts/library_bench.py measure --workers target/library-v5/workers-final \
  --candidate <candidate worker> --baseline target/library-v14/baseline-library_decode_reuse \
  --reuse --out target/library-v14/screen-<name> --corpus-manifest target/library-v11/real-corpus.json \
  --levels 6 --sessions 3 --minimum-ns 250000000 --study v14-screen-<name>   # final: --sessions 5
# x86-64: deflated-x86-perf:v13 image, --cap-add PERFMON --cap-add SYS_PTRACE
# --security-opt seccomp=unconfined, work pinned with taskset -c 1; references and
# workers as in v13, then the same measure command and
python3 scripts/library_x86_counters.py counters --workers target/library-v14/workers \
  --measure-run target/library-v14/measure-aa --core <base core> --accel <base accel> \
  --extra cand1=... --extra cand2=... --extra combo123-accel=... \
  --cpu 1 --out target/library-v14/counters --minimum-ns 500000000 --repeats 3
python3 scripts/archive_v14_decode_candidates.py
```

## Next

The largest remaining gap is instructions per byte against libdeflate:
1.49× on x86-64. libdeflate's remaining advantages include:

- multi-literal table entries
- an 8-bit distance root with subtables
- its own BMI2 build of the whole decompressor

Before any of that, the open measurement items remain:

- the batched-timer correction for small inputs
- small-gzip latency
- peak memory, including the subtable allocation
- independent holdout inputs on both architectures

A portable-CRC gzip path still trails zlib-ng on x86-64. The accelerator's
`crc32fast` path covers that case.
