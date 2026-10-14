# verified-deflate

A raw DEFLATE (RFC 1951) decoder and compressing encoder with gzip and minimal
single-entry ZIP framing in Rust. The portable core has zero runtime
dependencies; an optional accelerated crate supplies optimized backends. An
executable Lean 4 model describes the core semantics.

**Status: active library development (2026-10-14).** Work has resumed with
whole-buffer DEFLATE/GZIP decompression and a usable Rust API as the first
priority. Direct performance references are zlib-ng and libdeflate. See the
[library plan and measurement boundary](docs/library-roadmap.md) and the
[crate usage guide](crates/deflate-core/README.md). The
[reusable decoder report](docs/library-decode-v5-report.md) covers `Decompressor`,
its checks, and fair state/output reuse comparisons on pinned real files.
The [native source/AST audit](docs/native-decode-audit.md) identifies copy,
bit-buffer and checksum costs using the compiled ARM paths and profiles.
The [v6 implementation](docs/library-decode-v6-report.md) adds bounded batches,
packed decode tables and faster portable CRC. The
[v7 report](docs/library-decode-v7-report.md) measures next-action lookahead and
short copies. The [v8 report](docs/library-decode-v8-report.md) combines
native-style action entries, literal grouping and bit-buffer refill. The
[v9 report](docs/library-decode-v9-report.md) reduces match-copy checks and
separates small-distance copies: another 4% raw and 3.4% gzip on the six-file
arm64 development pool. Raw decoding exceeds the pinned zlib-ng build by about
11%; libdeflate remains about 37% faster raw. Native gzip decoding remains ahead,
and individual packets and tiny gzip calls can regress.
The latest [v10 report](docs/library-decode-v10-report.md) removes discarded
gzip header metadata and unnecessary header CRC work: short gzip latency falls
about 28–35%, with larger gains on optional headers. Large-buffer throughput
does not improve; paired raw results regress about 1%. The subsequent
[runtime profile](docs/library-decode-v10-profile.md) identifies substantial
per-call timer overhead in tiny-input timings; those are instrumented-worker
results pending batched-clock remeasurement.
The [v11 checksum backend report](docs/library-decode-v11-crc-accelerator.md)
adds an optional `deflate-accel` crate backed by `crc32fast`. It preserves the
portable core and improves reused GZIP throughput by 24.5% in a four-file
diagnostic; the measured pool beats zlib-ng and remains behind libdeflate.
A competitive release is a
target, not an established claim across workloads or architectures.

The earlier compression research remains closed and its immutable evidence is
retained. The [historical handover](docs/handover.md) and
[closure report](docs/new-methods-report.md) describe that study, not the scope
of the new library work.
- `crates/deflate-core/` — the decoder and encoder. `no_std`, no runtime
  dependencies, `#![forbid(unsafe_code)]`.
- `crates/deflate-accel/` — opt-in accelerated decoding; dependencies are kept
  outside the portable core.
- `spec/Deflate/` — the Lean 4 model and kernel-checked proofs, with headline
  theorems checked for standard axioms only,
  with no `sorry`, no `admit` and no `native_decide`.
- `oracles/` — a differential harness running `deflate-core`, the Lean model,
  and `zlib` over the same corpus, with optional `lean-zip` advisories.
- `fuzz/` — six core `cargo-fuzz` targets and two experimental DSC1 targets;
  see the [target descriptions](fuzz/README.md).

**What is proved, and what is not.** The theorems are statements about the
Lean model, not about the Rust binary. Nothing is extracted from or to Rust.
What connects them is the differential harness, which is test evidence over a
finite corpus. `vdeflate` is never "formally verified". Read
[docs/verification-boundary.md](docs/verification-boundary.md) before quoting
any correctness claim, and [docs/conformance.md](docs/conformance.md) for
feature-by-feature coverage.

Lean proves general decoder fuel non-exhaustion (`decode_never_exhausts`)
and custom block-splitting round trips (`decode_compressSplit`) for every
checked policy, alongside initial gzip and ZIP framing proofs.

## Build

    make          # cargo build --release + lake build
    make test     # cargo test, Lean gate, differential harness
    make fuzz     # 60s per fuzz target
    make size     # reproducible binary-size measurement
    make perf     # decode and compress throughput against miniz_oxide
    make profile  # where decode and encode time go (macOS, needs samply)
    make research-check # audit retained research tooling and artifacts

Needs Rust 1.88 (edition 2024), elan with Lean v4.30.0, and Python 3.
The optional optimizer campaign needs Python 3.12+ and a local research venv.

## Retained research

Historical compression research commands and reports are retained for reproduction.
They do not schedule new searches; `research-poc`, `research-search`, `research-campaign`
and `research-policy` explicitly run historical experiments when invoked.
The closed tuning investigation covered multidimensional parameter search,
GPU-assisted proposals, synthetic generators and verification gates. Its
bounded spikes and PoC are in
[docs/autotuning-investigation.md](docs/autotuning-investigation.md).
The validated parameter adapter, CPU search commands and first synthetic
results are in [docs/cpu-search-report.md](docs/cpu-search-report.md).
The larger mixed-workload experiment and full-file validation are in
[docs/cpu-search-campaign-report.md](docs/cpu-search-campaign-report.md).
The context-policy experiment, including negative adaptation findings, is in
[docs/context-policy-report.md](docs/context-policy-report.md). Completed stages
are recorded in [the completion audit](docs/autotuning-completion-audit.md).
The trained feature/latent ensembles and CPU/Metal crossover are compared in
[docs/trained-surrogate-report.md](docs/trained-surrogate-report.md).
The mixed-variable Bayesian comparison and observed wall-time frontiers are
in [docs/bayesian-search-report.md](docs/bayesian-search-report.md).
The exact fixed-cost oracle, native parser and eight hash/history layouts are
evaluated in [docs/encoded-cost-report.md](docs/encoded-cost-report.md), including
the rejected size/CPU tradeoff and reproducible synthetic construction witnesses.
The stored/fixed/dynamic block-type experiment and its Lean model boundary are
in [docs/mixed-block-report.md](docs/mixed-block-report.md).
The frozen ten-session final evaluation, direct miniz comparisons, RSS/linked-size
gates and retained size policy are in [docs/final-tuning-report.md](docs/final-tuning-report.md).

The CLI supports raw streams (`-c`, `-d`) and gzip (`-zc`, `-zd`).
`--stored` selects stored blocks for either compression mode; `--limit N`
bounds decompression, cumulatively across gzip members. ZIP creation and
extraction are library APIs in `deflate_core::zip`.

## Known gaps

- The default encoder uses a hash-chain matcher with one-step lazy matching and
  per-block dynamic or fixed Huffman codes (16384 tokens by default; stored
  when smaller). `deflate_with_level` exposes Fast, Balanced (the default),
  and Best presets for different speed/size tradeoffs. They use four-byte
  chains with separate short-match coverage; Best also tunes block splits.
  See the corpus measurements in [docs/tuning-report.md](docs/tuning-report.md)
  and the synthetic baseline in [docs/perf-report.md](docs/perf-report.md).
  `decode (compress find lf x) = x`
  is proved in Lean for every finder, every length heuristic `lf` and every
  input; the Rust encoder is linked to it by mirroring and differential
  testing only, and the length heuristic is unproved but checked, with a fixed
  fallback (ADR 0007). `lean-zip` is not installed here, so it contributes
  no differential result.
- Decode speed varies by input: stored and repeating streams outperform
  miniz_oxide on this machine, while text remains slower.
  [docs/perf-report.md](docs/perf-report.md) has the
  baseline, the profile, and the ranked candidates.
- ZIP supports one stored or DEFLATE entry on one disk, including standard
  data descriptors. ZIP64 and encryption are unsupported. Lean proves
  round trips for minimal single-member gzip and canonical single-entry
  stored ZIP; optional gzip headers, concatenation, ZIP DEFLATE entries and
  descriptors remain outside those framing models.
- No refinement proof connects the Lean model and the Rust code. ADR 0003
  records the Charon/Aeneas spike result.
