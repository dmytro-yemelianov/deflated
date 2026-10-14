# Maintenance handover

## Current handover — 2026-10-14

Library development has resumed with a focus on a Rust DEFLATE/GZIP
decompression library that can compete with zlib-ng and libdeflate. The active
scope and priorities are in the [library roadmap](library-roadmap.md). The
latest implementation and benchmark evidence are in the
[v11 CRC accelerator report](library-decode-v11-crc-accelerator.md).

The workspace now has an optional `deflate-accel` crate alongside
`deflate-core`. The core remains `no_std`, dependency-free, and free of unsafe
code. It exposes a GZIP CRC callback seam; the accelerator uses `crc32fast`
through that seam while leaving raw DEFLATE decoding in the portable core. This
keeps the optimized dependency out of core users' builds.

On the recorded Apple M5 benchmark pool, the accelerated decoder improved GZIP
throughput by 24.5% over the rebuilt current core and by 9.4% over zlib-ng.
libdeflate remained about 43% faster than the accelerator. Raw-DEFLATE results
were also measured, and CRC microbenchmarks show that hardware acceleration is
most useful for medium and large buffers. These are diagnostic results from
four historical inputs, not holdout or release evidence; see the report for
the exact protocol and limitations. The immutable receipt is
`scripts/reports/library-decode-v11-crc-accelerator.json.gz`.

The v11 build, Clippy, formatting, receipt/hash, and benchmark contract checks
passed. A follow-up on 2026-10-14 added `deflate-accel` equivalence tests
(result, output bytes, errors and output clearing must match the core on valid,
multi-member, CRC/ISIZE-corrupted, truncated, suffixed and limit-bounded
packets) and an `accel_gunzip` fuzz target; `gzip_header` and `accel_gunzip`
now run in `make fuzz`. Formatting, all-features Clippy, `make test` (Rust,
Lean, differential and framing oracles), the new accelerator tests and all ten
60-second `make fuzz` targets passed with no findings. This is correctness
evidence on one arm64 host; it does not make v11 a release candidate under the
roadmap's release gate.

The [v12 hot-loop screen](library-decode-v12-report.md) then inspected the raw
decode loop and screened three safe match-path changes. None improved paired
medians, so none was kept, and sources are unchanged. An A/A run showed that
pooled MB/s on a busy host moves by several percent between identical binaries.
Gate future screens on paired medians as well. Its receipt is
`scripts/reports/library-decode-v12-hot-loop.json.gz`.

The [v13 x86-64 counter attribution](library-decode-v13-x86-counters.md) ran
Linux `perf` on a shared i7-8700 host inside a container that had only
CAP_PERFMON added. On that host the core trails zlib-ng (394 vs 487 MB/s raw),
and libdeflate is 1.75× faster than the core. The gap is mostly instruction
count: 1.5–1.6× libdeflate's instructions per token, at 6–13% lower IPC.
Smaller contributions come from mispredicts (1.4–1.7× per token; about a
quarter of them at the conditional refill) and from L1D load misses (about
3× per byte; 62–71% at the 16 KiB literal/length table). An x86-64-v3 build
cuts instructions by 9% per raw byte. No source changed. The receipt is
`scripts/reports/library-decode-v13-x86-counters.json.gz`; arm64 counters
were not measured.

Next work should target those measured costs. Screen each candidate
separately with paired medians on both arm64 and x86-64:

1. A 10–11-bit literal/length root table with a second-level path.
2. A branch-free fast-loop refill.
3. A BMI2 path in `deflate-accel`. This needs a design decision on the
   accelerator's unsafe and target-feature boundary.

Then measure table/setup overhead and memory, and add independent holdout
inputs before making broader performance claims. Keep the portable core usable
without optional dependencies, and compare against both native libraries using
the existing pinned, alternating benchmark protocol. See the roadmap for
sequencing and acceptance criteria.

## Historical record: 2026-10-07 closure

The compression campaigns and their source/measurement locks remain historical.

Date: 2026-10-07. The maintainer ended active compression research and moved
the project to maintenance mode. This is a scope cancellation, not completion
of every item in the former research plan. No new matcher, GPU search or codec
campaign is scheduled. The repository and its evidence are retained.

## What to maintain

- `crates/deflate-core`: existing raw DEFLATE encoder/decoder, gzip and minimal
  single-entry ZIP support; `no_std`, no runtime dependencies, no unsafe code.
- `crates/vdeflate`: the existing CLI. Its interfaces and formats are unchanged
  by this closure.
- `spec/Deflate`: executable Lean model and kernel-checked proofs.
- `oracles`, `tests`, `fuzz`, and CI: differential, framing, regression and
  bounded fuzz checks connecting the implementations through finite evidence.

The [verification boundary](verification-boundary.md) is mandatory context:
there is no Rust-to-Lean refinement proof. Rust binaries are not formally
verified by the model's theorems. ZIP64 and encryption are unsupported; several
gzip/ZIP framing features remain outside the proved model.

`crates/structured-codec` and `tools/new-methods-*` are unpublished research
artifacts. DSC1 has byte-exact test evidence but no complete transform/frame
model proof and no qualifying performance result. Do not promote it to a
production codec or present it as an improvement over zstd.

## Results worth preserving

The completed [encoder investigation](encoder-improvement-report.md) retained
portable bit-code reversal: 1.032× warm and 1.038× first-call encode speed on
its eight held real inputs, with identical packets. This is a previous result,
not a gain from the final new-methods campaign. Its main 1.5×/+1% target failed.

The [final campaign report](new-methods-report.md) records all 12 DSC1 settings
as rejected after one training screen. The best size variant is +8.52% bytes,
38.58× slower warm encoding and 21.69× longer warm decoding than checksummed
zstd-3 on the eight B training groups. These are training point estimates.
The proposed A matcher has a specification only: implementation and evaluation
were cancelled. It is untested, not an experimentally rejected algorithm.

## Evidence and working state

The pre-closure revision is
`dfb372485937a77d4e7fe497a8764e73fb06de72`; its
[exact CI run passed](https://github.com/dmytro-yemelianov/deflated/actions/runs/37679215741).
The closure change adds documentation, the completed B measurement ledger and
its CI audit. It does not alter Rust/Lean codec sources or frozen worker inputs.
Check the [CI workflow](https://github.com/dmytro-yemelianov/deflated/actions/workflows/ci.yml)
for the closure commit's own result; the earlier run does not validate later
changes.

The new-methods control is
`b7d5e0fc79f4f72d2ba772312ec9a22497699ed5`. It already contains the accepted
reversal improvement. The immutable locks are
[`new-methods-reference-lock.json`](../scripts/reports/new-methods-reference-lock.json)
and [`new-methods-decoder-lock.json`](../scripts/reports/new-methods-decoder-lock.json).
Do not edit source files bound by these receipts to repair an audit. Preserve
the historical source and use separately versioned inputs for any later study.

Committed reports contain source pins, recipes, licenses, hashes, configuration
rosters and compressed measurement rows. Large source bodies, SDK builds,
packets and host-specific binaries remain in ignored `target/`. In particular:

| Local directory | Contents |
| --- | --- |
| `target/new-methods/baseline-b7` | Archived b7 source and sealed binaries |
| `target/new-methods/references-v1` | Seven isolated native SDK builds |
| `target/new-methods/native-workers-v1` | Frozen native codec workers |
| `target/new-methods/rust-workers-v1` | Frozen original Rust workers |
| `target/new-methods/decode-workers-v1` | Decoder-only timer supplement |
| `target/new-methods/corpus-v1` | Licensed real source bodies and receipts |
| `target/new-methods/synthetic-v1` | Deterministic synthetic/stress bodies |
| `target/new-methods/b-training-v1` | Complete B screen and encoded packets |

These directories were not purged by closure. Binary hashes/timings depend on
the original Apple M5/macOS 27.2 host, Rust 1.88.0 and recorded compiler flags.
Recipes permit reconstruction; they do not promise identical timing on another
machine. Rebuilding a worker alone does not recreate a historical measurement.
Real corpus bodies are not redistributed. Unrelated `memory/` and `.DS_Store`
files were left untouched.

At handover, `main` is the only registered worktree. The decoder tool's nested
Cargo `target/` is now ignored; no worktree or build/data directory was deleted.

## Maintenance checks

Use Rust 1.88 or the repository's compatible toolchain, elan/Lean 4.30.0 and
Python 3. Full optional optimizer reproduction uses Python 3.12+ and its pinned
requirements. Follow CI for the complete current gate.

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
make test
python3 scripts/new_methods_reference_lock.py --check
python3 scripts/new_methods_decoder_lock.py --check
python3 scripts/test_new_methods_data_artifacts.py
python3 scripts/new_methods_b_publish.py --check
```

On the original machine, add `--local` to each lock audit and run
`python3 scripts/new_methods_b_publish.py --check --local` to check cached
worker, raw-input and packet hashes. `make fuzz` runs the ten bounded targets;
CI also checks default-feature Clippy, research artifacts and decoder contracts.
No extra benchmark campaign is needed for this documentation-only closure.

## Unfinished scope and restart conditions

Cancelled work includes all 20 A configurations, A scalar/state/token/packet
equivalence, three-session validation, final held evaluation, new-study RSS
qualification, full DSC1 transform/frame proofs and production promotion.
The [closure table](new-methods-report.md#stage-disposition) keeps these distinct
from completed stages. No sentinel was selected; validation/held bodies were
not used for codec screening or fitting. Acquisition and integrity/deduplication
checks are not held performance evaluation.

The former goal's tracker was paused at closure. Its original all-stage
objective was not achieved and must not be marked achieved merely because
research stopped. The maintainer's replacement deliverable is this handover,
updated entry points and preserved negative evidence.

Resume research only for an explicit practical workload and a bounded new
objective. Reuse old measurements as regression evidence, retain cancelled
specifications as historical designs, and preregister any changed protocol
before evaluation. There is no established universal speed/ratio advantage,
new compression principle or end-to-end GPU benefit to build a release claim on.
