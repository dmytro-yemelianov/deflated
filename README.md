# verified-deflate

A raw DEFLATE (RFC 1951) decoder and compressing encoder with gzip and minimal
single-entry ZIP framing in Rust, with zero
runtime dependencies, beside an executable Lean 4 model of the same semantics.

- `crates/deflate-core/` — the decoder and encoder. `no_std`, no runtime
  dependencies, `#![forbid(unsafe_code)]`.
- `spec/Deflate/` — the Lean 4 model and kernel-checked proofs, with headline
  theorems checked for standard axioms only,
  with no `sorry`, no `admit` and no `native_decide`.
- `oracles/` — a differential harness running `deflate-core`, the Lean model,
  and `zlib` over the same corpus, with optional `lean-zip` advisories.
- `fuzz/` — five persistent `cargo-fuzz` targets: `inflate`, `dynamic_header`, `differential`, `roundtrip`, `dynamic_lengths`.

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
    make research-check # autotuning-tool integrity checks, no GPU dependency
    make research-poc   # seeded synthetic corpus and finite tuning pilot

Needs Rust 1.88 (edition 2024), elan with Lean v4.30.0, and Python 3.

The next tuning investigation covers multidimensional parameter search,
GPU-assisted proposals, synthetic generators and verification gates. Its
bounded spikes and runnable PoC are in
[docs/autotuning-investigation.md](docs/autotuning-investigation.md).

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
