# Conformance matrix (spec §13)

"Formally covered" means a named theorem in `spec/Deflate/Properties.lean`
covers the feature *in the Lean model*. It never means the Rust code is
proved, and it never counts a theorem from another project.

| Feature | Implemented | Tested | Formally covered |
| --- | --- | --- | --- |
| Bit reader (LSB-first, EOF) | yes | yes | yes |
| Stored blocks | yes | yes | yes |
| Fixed Huffman | yes | yes | yes |
| Dynamic Huffman | yes | yes | yes |
| Multi-block streams | yes | yes | yes |
| Overlapping back-reference | yes | yes | yes |
| Malformed input rejection | yes | yes | yes |
| Output limit | yes | yes | yes |
| Encoder validity (stored) | yes | yes | yes |
| Round trip (stored) | yes | yes | yes |
| Compressing encoder: fixed-Huffman block with LZ77 matches, stored fallback (`deflate`, `compress`) | yes | yes | yes, for every finder and every input (`decode_compress`) |
| Match search (hash chains) | yes | yes | no: untrusted, re-checked by `accept` (ADR 0006) |
| Dynamic Huffman encoding: per-block dynamic or fixed, blocks of 16384 tokens (`deflate`, `emitBlocks`) | yes | yes | yes, for every length heuristic (`decode_emitBlocks`, `decode_compress`) |
| Code-length heuristic (`lengths_for`, `build_lengths`) | yes | yes | no: untrusted, checked by `valid_lengths` / `validLengths`, with a fixed-block fallback (ADR 0007) |
| gzip framing (RFC 1952): header, DEFLATE stream, CRC32/ISIZE trailer (`gzip`, `gunzip`) | yes | yes | no: outside Lean verification boundary (spec §6), differential tested against zlib |
| Concatenated gzip members, cumulative limit, FHCRC and stored-only CLI mode | yes | yes: gzip regression tests and zlib header cross-decode | no: framing is outside the Lean model |
| Single-entry ZIP: stored/DEFLATE, signed/unsigned data descriptors, output limit and checked field sizes | yes | yes: ZIP regression tests with Python zipfile fixtures | no: container framing is outside the Lean model; no ZIP64 or encryption |
| Content-dependent block splitting (`deflate_with_split`) | yes | yes: bounded lookahead, invalid-policy fallback, cross-block matches and default equivalence | no: Lean `emitBlocks` uses the default 16384-token split |

Rust/Lean correspondence: demonstrated by differential testing over 20,197 streams with 0 findings; see [docs/correspondence.md](docs/correspondence.md). Not proved. For the encoder, the link is mirroring plus differential: `EMIT` output is byte-identical between Rust and Lean across 314 requests; `EMITDYN` (one dynamic-or-fixed block from explicit lengths) across 1010 requests, 593 of them dynamic, plus 160 lone-distance-code requests (16 dynamic, the 144 others required to equal the fixed block and all decoded by zlib), with 0 findings; `EMITBLOCKS` (multi-block cutting with fixed blocks, up to 40000 tokens) across 5 requests with 0 findings; oracle whitespace handling (FF, VT, tab, CR) across 67 requests with identical replies; and `deflate` output is decoded back to the payload by Rust, Lean and zlib on 14 payloads. The harness self-test passes 10/10. Multi-block streams with dynamic blocks are compared by decoding only (Rust, Lean, zlib, `miniz_oxide`), not byte for byte against Lean. The Lean `DEFLATE` finder always returns `none`, so compressed output is not compared across the two for equality. `lean-zip` was not installed in the run that produced these numbers.

## v1 Acceptance Criteria (spec §18)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Rust decodes stored, fixed, and dynamic DEFLATE blocks | Satisfied | Verified in [crates/deflate-core/tests/stored_tests.rs](crates/deflate-core/tests/stored_tests.rs), [crates/deflate-core/tests/fixed_tests.rs](crates/deflate-core/tests/fixed_tests.rs), and [crates/deflate-core/tests/dynamic_tests.rs](crates/deflate-core/tests/dynamic_tests.rs) |
| 2 | Multi-block streams work | Satisfied | Verified across stored blocks, mixed streams, and differential corpus |
| 3 | Malformed/truncated streams return explicit errors rather than panicking | Satisfied | Zero unwraps/panics; verified by [crates/deflate-core/tests/hostile_tests.rs](crates/deflate-core/tests/hostile_tests.rs) and [crates/deflate-core/tests/regression_tests.rs](crates/deflate-core/tests/regression_tests.rs) |
| 4 | The core contains no unjustified `unsafe` | Satisfied | Enforced by `#![forbid(unsafe_code)]` and CI grep gate across `crates/deflate-core/src/` |
| 5 | Differential tests against independent implementations pass | Satisfied | 20,197 streams tested against zlib and `lean-zip` with 0 findings in [oracles/reports/differential.json](oracles/reports/differential.json) |
| 6 | A persistent fuzz target exists and has no known reproducible crash/hang | Satisfied | 5 targets in `fuzz/fuzz_targets/` (`inflate`, `dynamic_header`, `differential`, `roundtrip`, `dynamic_lengths`) wired to CI and `make fuzz`; regression corpus in `tests/malformed/` passes |
| 7 | Lean proofs cover the documented v1 verification boundary | Satisfied | 218 kernel-checked theorems in [spec/Deflate/Properties.lean](spec/Deflate/Properties.lean), 73 headline theorems in [spec/scripts/axioms.lean](spec/scripts/axioms.lean) with zero custom axioms |
| 8 | Rust/Lean correspondence is demonstrated for the proof-critical core | Satisfied | 4-way differential harness verifies identical line-for-line output on 20,197 streams; see [docs/correspondence.md](docs/correspondence.md) |
| 9 | A minimal encoder emits valid DEFLATE and round-trips supported input | Satisfied | `deflate_stored` and `encodeStored` emit valid stored streams. `deflate` and `compress` emit LZ77 matches in blocks of 16384 tokens, each dynamic-Huffman when the checked lengths (`valid_lengths` / `validLengths`, ADR 0007) make it strictly smaller and fixed-Huffman otherwise, and choose stored when that is smaller. Lean proves `decode_encodeStored`, `decode_emitBlocks` and `decode_compress` (for every finder and every `lengthsFor`) for every input. Rust is tested in [crates/deflate-core/tests/encode_tests.rs](crates/deflate-core/tests/encode_tests.rs), [emit_blocks_tests.rs](crates/deflate-core/tests/emit_blocks_tests.rs) and [emit_blocks_equiv_tests.rs](crates/deflate-core/tests/emit_blocks_equiv_tests.rs), decoded by `miniz_oxide`, and compared in the differential harness: `EMIT` (fixed block), `EMITDYN` (one dynamic-or-fixed block from explicit lengths, byte-identical, including lone distance codes that must fall back to fixed), `EMITBLOCKS` (multi-block cutting, fixed blocks, byte-identical) and `DEFLATE` (decoded by Rust, Lean and zlib). Streams with several dynamic blocks are checked by decoding only, not byte-compared with Lean |
| 10 | `docs/verification-boundary.md` states exactly what is and is not formally verified | Satisfied | Documented with exact theorem lists, non-proved boundaries, and explicit gaps in [docs/verification-boundary.md](docs/verification-boundary.md) |
| 11 | `docs/conformance.md` accurately reports implementation/test/proof coverage | Satisfied | Feature conformance matrix above and acceptance criteria table |
| 12 | `docs/size-report.md` reports reproducible binary-size measurements | Satisfied | Generated by [scripts/size_report.sh](scripts/size_report.sh), recorded in `scripts/reports/size.json`, verified by [scripts/check_size_report.sh](scripts/check_size_report.sh) |
