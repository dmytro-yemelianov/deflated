# Rust/Lean correspondence (P9)

Spec §9 P9 asks for `RustDecode(stream) = LeanDecode(stream)` on the
supported domain, and §18.8 asks that correspondence be *demonstrated*, not
asserted. This document states exactly what was demonstrated and how.

## What was demonstrated

For every stream in the corpus below, `deflate_core::inflate_with_limit` and
`Deflate.decode` — the same definition the theorems in
`spec/Deflate/Properties.lean` are about — returned the same outcome:
byte-identical output on success, and the same named error on failure.

| Source | Streams |
| --- | ---: |
| zlib, levels 0–9, 20+ payloads | 84 |
| Truncations at power-of-two cuts | 816 |
| Single-bit mutations | 556 |
| Hand-built boundary cases | 18,741 |
| **Total** | **20,197** |

Findings: **0**. Raw results: `oracles/reports/differential.json`.

Independently, three `cargo-fuzz` targets have run with no reproducible crash or hang, and `tests/malformed/` replays every minimized finding on every `cargo test`.

## What was not demonstrated

This is **test evidence over a finite corpus**, not a proof. It says nothing
about streams the corpus never produced. There is no refinement proof
connecting `crates/deflate-core` to `spec/Deflate/`; see ADR 0003 for the
Charon/Aeneas spike result and `docs/verification-boundary.md` for the
boundary as a whole.

In spec §2's terms, this document supports exactly one of the five claim
categories — Rust/Lean correspondence — and supports it empirically.

## Why zlib agreement is not the same thing

zlib is the de facto definition of DEFLATE. Agreeing with it demonstrates
*interoperability*, which is what §12 asks differential testing for. It
cannot demonstrate *conformance*, because where zlib and RFC 1951 differ,
zlib wins in practice and a test against zlib cannot see the difference. The
hand-built corpus and the `lean-zip` advisories exist for that reason.
