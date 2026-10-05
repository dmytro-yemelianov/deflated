# verified-deflate

A raw DEFLATE (RFC 1951) decoder and compressing encoder in Rust, with zero
runtime dependencies, beside an executable Lean 4 model of the same semantics.

- `crates/deflate-core/` — the decoder and encoder. `no_std`, no runtime
  dependencies, `#![forbid(unsafe_code)]`.
- `spec/Deflate/` — the Lean 4 model and 142 theorems about it (54 of them headline theorems checked for standard axioms only), kernel-checked,
  with no `sorry`, no `admit` and no `native_decide`.
- `oracles/` — a differential harness running `deflate-core`, the Lean model,
  `zlib` and `lean-zip` over the same corpus.
- `fuzz/` — four persistent `cargo-fuzz` targets: `inflate`, `dynamic_header`, `differential`, `roundtrip`.

**What is proved, and what is not.** The theorems are statements about the
Lean model, not about the Rust binary. Nothing is extracted from or to Rust.
What connects them is the differential harness, which is test evidence over a
finite corpus. `vdeflate` is never "formally verified". Read
[docs/verification-boundary.md](docs/verification-boundary.md) before quoting
any correctness claim, and [docs/conformance.md](docs/conformance.md) for
feature-by-feature coverage.

## Build

    make          # cargo build --release + lake build
    make test     # cargo test, Lean gate, differential harness
    make fuzz     # 60s per fuzz target
    make size     # reproducible binary-size measurement
    make perf     # decode and compress throughput against miniz_oxide
    make profile  # where decode time goes (macOS, needs samply)

Needs Rust 1.88 (edition 2024), elan with Lean v4.30.0, and Python 3.

## Known gaps

- The encoder uses a greedy hash-chain matcher and fixed Huffman codes
  (or stored blocks when smaller). No dynamic Huffman block and no lazy
  matching yet, so ratio is between miniz_oxide levels 1 and 6 on text and
  speed is below both. See the Compression section of
  [docs/perf-report.md](docs/perf-report.md). `decode (compress find x) = x`
  is proved in Lean for every finder and input; the Rust encoder is linked to
  it by mirroring and differential testing only (ADR 0006).
- No optimization yet: decoding is slower than miniz_oxide on every input
  measured. [docs/perf-report.md](docs/perf-report.md) has the
  baseline, the profile, and the ranked candidates.
- No gzip (RFC 1952) or ZIP framing (spec §17 M9, M10).
- No refinement proof connects the Lean model and the Rust code. ADR 0003
  records the Charon/Aeneas spike result.
- Explicit verification gaps in the Lean model: P8 fuel non-exhaustion is recorded in [docs/verification-boundary.md](docs/verification-boundary.md).
