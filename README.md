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
  `zlib` and `lean-zip` over the same corpus.
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
    make profile  # where decode time goes (macOS, needs samply)

Needs Rust 1.88 (edition 2024), elan with Lean v4.30.0, and Python 3.

The CLI supports raw streams (`-c`, `-d`) and gzip (`-zc`, `-zd`).
`--stored` selects stored blocks for either compression mode; `--limit N`
bounds decompression, cumulatively across gzip members. ZIP creation and
extraction are library APIs in `deflate_core::zip`.

## Known gaps

- The encoder uses a hash-chain matcher with one-step lazy matching and
  per-block dynamic or fixed Huffman codes (16384 tokens by default; stored
  when smaller). The published measurements predate the lazy matcher and
  decoder table changes. On the text corpus the measured ratio is 0.3705 against 0.5698 for
  miniz_oxide level 1 and 0.3633 for level 6 (M7a's fixed-only encoder: 0.4744),
  and speed is below both. See the Compression section of
  [docs/perf-report.md](docs/perf-report.md). `decode (compress find lf x) = x`
  is proved in Lean for every finder, every length heuristic `lf` and every
  input; the Rust encoder is linked to it by mirroring and differential
  testing only, and the length heuristic is unproved but checked, with a fixed
  fallback (ADR 0007). `lean-zip` is not installed here, so it contributes
  no differential result.
- The published decode baseline is slower than miniz_oxide on every input
  measured. [docs/perf-report.md](docs/perf-report.md) has the
  baseline, the profile, and the ranked candidates.
- ZIP supports one stored or DEFLATE entry on one disk, including standard
  data descriptors. ZIP64 and encryption are unsupported. Lean proves
  round trips for minimal single-member gzip and canonical single-entry
  stored ZIP; optional gzip headers, concatenation, ZIP DEFLATE entries and
  descriptors remain outside those framing models.
- No refinement proof connects the Lean model and the Rust code. ADR 0003
  records the Charon/Aeneas spike result.
