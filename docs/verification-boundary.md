# Verification boundary

What this document means by each claim, per spec §2. Read it before quoting
any correctness claim about this project.

## What is proved

Named theorems in `spec/Deflate/Properties.lean`, kernel-checked by Lean
4.30.0 with no `sorry`, no `admit` and no project-defined axiom. CI fails if
any of those appear, and fails if `#print axioms` shows a headline theorem
depending on `sorryAx`.

These theorems are statements about **the Lean model in `spec/Deflate/`**.

## What is not proved

- **The Rust code.** No refinement proof connects `crates/deflate-core` to
  the Lean model for milestones M1–M8. Following the M0 Charon/Aeneas spike
  outcome (ADR 0003), the differential harness in `oracles/` is the primary
  bridge, providing test evidence over a finite corpus. It says nothing
  about streams the corpus does not contain.
- **The executable.** File I/O, argument parsing, process startup, the
  allocator, the linker and the compiler are all outside the boundary
  (spec §6). `vdeflate` is never "formally verified".
- **`lean-zip` (commit `2f7a63f38195bc667a926881b55d10c9f8a88eeb`).** Its theorems are about its own Lean code. They never
  appear in the "Formally covered" column of `docs/conformance.md`
  (spec §13). It is used here as an independent reading of RFC 1951 in the
  differential harness.
- **Hash and arithmetic idealizations.** Where the model represents a
  quantity more abstractly than the Rust does, this document names it.

## Proved theorems in the Lean model

As of Milestone M7b, the following headline theorems in `spec/Deflate/Properties.lean` are kernel-checked with zero custom axioms:

- **P1 (Bit reader):** `byteAt_oob`, `readBits_pos`, `readBits_bytes`, `readBits_lt`, `readBits_eof`, `alignToByte_idem`.
- **P2 (Canonical Huffman):** `fixedLitLen_complete`, `fixedDist_complete`, `decodeSym_pos`, `decodeSym_bytes`, `decodeSym_in_range`.
- **P2 (Table-driven Huffman, ADR 0005):** `decodeSymFast_eq` (the table fast path equals `decodeSym` on every reader, results and errors alike), `decodeSym_local`, `buildTable_size`, `tableEntry_some`, `readBits_some`, `fixedLitLen_table_total`, `fixedDist_table_total`.
- **P3 (Block headers & stored blocks):** `readHeader_pos`, `readStored_aligned`, `readStored_consumes`, `readStored_rejects_bad_nlen`.
- **P4 (Huffman block body):** `decodeHuffBlock_monotone`, `decodeHuffBlock_within_limit`, `decodeHuffBlock_progress`.
- **P5 (Dynamic Huffman tables):** `clOrder_is_a_permutation`, `readDynamicCodes_valid`, `readDynamicCodes_pos`.
- **P6 & P7 (LZ77 back-references):** `copyBack_size`, `copyBack_overlap`, `copyBack_rejects`, `readLength_range`, `readDistance_range`.
- **P10 & P11 (Encoder validity and round trip):** `decode_encodeStored` (every input round-trips through the stored encoder, multi-block inputs over 65535 bytes included: `x.size ≤ limit → decode (encodeStored x) limit = .ok x`). This closed the stored-encoder P11 gap that earlier versions of this document recorded, with `encodeStored_empty` and `encodeStored_valid` as corollaries for empty input.
- **P11 (Compressed encoder, M7a/M7b):** `decode_compress` (the model compressor round-trips every input for every finder and every `lengthsFor`: `x.size ≤ limit → decode (compress find lengthsFor x) limit = .ok x`), resting on `decode_emitBlocks` (below), `decode_emitFixed` (a valid token list emitted as one fixed-Huffman block decodes to its expansion), `expand_compressTokens` and `compressTokens_valid` (the matcher re-checks every finder candidate, so tokenization is lossless and valid even for an adversarial finder).
- **P11 (Dynamic-Huffman encoder, M7b):** `decode_emitBlocks` (a valid token list emitted as blocks of at most 16384 tokens, each dynamic or fixed as the untrusted `lengthsFor` and `validLengths` decide, decodes to its expansion: `Valid ts → (expand ts).size ≤ limit → decode (emitBlocks lf ts) limit = .ok ⟨expand ts⟩`). It rests on `decodeSym_canonical` and `decodeSym_of_canonical_bits` (the decoder reads back every canonical code `canonicalCode` writes), `canonicalCode_fixedLit` and `canonicalCode_fixedDist`, `rleLengths_expand` and `rleLengths_inRange` (the code-length RLE), `readCodeLengths_go_emit`, `readCLLens_go_emit` and `readDynamicCodes_emitHeader` (the decoder reads back the header `emitHeader` writes), `validLengths_spec`, `huffLoop`, `readHeader_written`, `decodeBlock_emitFixedBlock`, `decodeBlock_emitDynamicBlock`, `decodeBlock_emitBlock` and `decodeFuelLoop_emitBlocksGo`. `emitBlocks_none` and `compress_none` show that with `lengthsFor := fun _ => none` and at most 16384 tokens the output is M7a's single fixed block. The length heuristic is not proved and need not be: every length set it returns is checked by `validLengths`, and a rejected one falls back to fixed.
- **P12 (Determinism & output limits):** `decode_deterministic`, `decode_within_limit`.

## The encoder boundary

For the encoder, as for the decoder, the Lean model is proved and the Rust is
not. The link is **mirroring plus differential testing, and nothing more**:

- `accept`, `emitFixed`, `compressTokens` and `compress` in Lean have Rust
  counterparts (`matcher::accept`, `emit_fixed`, `deflate`) written to match
  them, with the Lean name in the comment. For M7b the same holds for
  `canonicalCode`, `rleLengths`, `emitHeader`, `validLengths`,
  `emitDynamicBlock`, `emitBlock` and `emitBlocks`; the oracle command
  `EMITDYN` exposes one dynamic-or-fixed block from given lengths in both.
- The harness sends `EMIT` token lists to Rust and Lean and requires
  byte-identical output (314 requests, 0 findings), `EMITDYN` requests
  (explicit lit, dist and CL lengths; 1010 requests, 593 of them dynamic,
  0 findings) and `EMITBLOCKS` requests (up to 40000 tokens, 5 requests,
  0 findings). Its self-test, which checks that a corrupted Rust reply is
  detected, passes 9/9. It sends `DEFLATE`
  payloads and requires that Rust, Lean and zlib each decode every produced
  stream back to the payload (14 payloads, 0 findings). The Lean `DEFLATE`
  finder always returns `none`, so the harness does not compare the two
  encoders' compressed output for equality.
- The Rust hash-chain matcher is not proved, and need not be: `decode_compress`
  holds for every finder (ADR 0006). What a bad finder can affect is ratio and
  time, not round-trip correctness in the model.
- The length heuristic (`build_lengths`, `lengths_for`) is unproved. Its
  results are checked by `valid_lengths` before use and a rejected set falls
  back to fixed (ADR 0007), so a wrong heuristic costs ratio. That the Rust
  `valid_lengths` and emitter mirror the Lean ones rests on the differential
  evidence above.
- `lean-zip` was not installed in the run that recorded these numbers, so no
  `lean-zip` result is claimed for the encoder.

## Explicit verification gaps

- **P8 (Fuel non-exhaustion):** Still open in general. The model entry point `Deflate.decode` supplies `8 * bs.size + 1` fuel. Because each block consumes at least 3 header bits and each Huffman step consumes at least 1 bit, exhaustion is unreachable on any finite input. Fully formalizing this non-exhaustion invariant across `readCodeLengths.go`, `decodeHuffBlock`, and `decodeFuelLoop` is deferred. The general decoder gap is recorded here as an honest gap per plan Task 18 Step 4; fuel sufficiency is proved for the encoder functions `emitFixed`, `encodeStored` and, in M7b, the block loop `emitBlocks` (`decodeFuelLoop_emitBlocksGo`).
- **Table-driven Huffman decoding (ADR 0005):** no gap in the Lean model: `decodeSymFast_eq` is the full equivalence, with no hypothesis on the code or the reader. The model's block decoder still calls `decodeSym`, and `decodeSymFast` is a separate definition proved equal to it. What is not proved is that the Rust table and peek mirror `buildTable` and `decodeSymFast`. Like the rest of the Rust, that rests on tests and the differential harness (ADR 0003), plus the unit test ADR 0005 asks for, which compares the Rust table against the by-evaluation construction.

## Status

Milestones M0–M6, M7a, M8 complete (v1 milestone reached); M7b (dynamic-Huffman encoder) complete (ADR 0007). Decoder, stored encoder, Lean formal model with 218 kernel-checked theorems (73 headline theorems registered in `spec/scripts/axioms.lean`), the compressing encoder with `decode_compress` (M7a fixed blocks, generalized in M7b to dynamic blocks through `decode_emitBlocks`), 4-way differential harness (20,197 streams, 0 findings), fuzz targets, size reports, and CLI all complete and passing CI gates.
