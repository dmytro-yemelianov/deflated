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

As of Milestone M5 (Task 18), the following headline theorems in `spec/Deflate/Properties.lean` are kernel-checked with zero custom axioms:

- **P1 (Bit reader):** `byteAt_oob`, `readBits_pos`, `readBits_bytes`, `readBits_lt`, `readBits_eof`, `alignToByte_idem`.
- **P2 (Canonical Huffman):** `fixedLitLen_complete`, `fixedDist_complete`, `decodeSym_pos`, `decodeSym_bytes`, `decodeSym_in_range`.
- **P3 (Block headers & stored blocks):** `readHeader_pos`, `readStored_aligned`, `readStored_consumes`, `readStored_rejects_bad_nlen`.
- **P4 (Huffman block body):** `decodeHuffBlock_monotone`, `decodeHuffBlock_within_limit`, `decodeHuffBlock_progress`.
- **P5 (Dynamic Huffman tables):** `clOrder_is_a_permutation`, `readDynamicCodes_valid`, `readDynamicCodes_pos`.
- **P6 & P7 (LZ77 back-references):** `copyBack_size`, `copyBack_overlap`, `copyBack_rejects`, `readLength_range`, `readDistance_range`.
- **P10 & P11 (Encoder validity and round trip):** `encodeStored_empty`, `encodeStored_valid`.
- **P12 (Determinism & output limits):** `decode_deterministic`, `decode_within_limit`.

## Explicit verification gaps

- **P8 (Fuel non-exhaustion):** The model entry point `Deflate.decode` supplies `8 * bs.size + 1` fuel. Because each block consumes at least 3 header bits and each Huffman step consumes at least 1 bit, exhaustion is unreachable on any finite input. Fully formalizing this non-exhaustion invariant across `readCodeLengths.go`, `decodeHuffBlock`, and `decodeFuelLoop` is deferred; rather than admitting it with `sorry` or papering over it, it is recorded here as an honest gap per plan Task 18 Step 4.
- **P10 & P11 (Symbolic & multi-chunk round trip):** `encodeStored_empty` proves that empty input produces a valid RFC 1951 stream that decodes to the empty array (`decode (encodeStored ⟨#[]⟩) limit = .ok ⟨#[]⟩`), and `encodeStored_valid` confirms its validity. Multi-chunk and non-empty symbolic round trip is covered empirically across 20,000+ streams by the differential harness in `oracles/` (Milestone M6), while formal induction across 32-bit little-endian bit-reader state transitions for arbitrary symbolic payloads is deferred, per plan Task 21 Step 5.

## Status

Milestones M0–M6, M8 complete (v1 milestone reached). Decoder, stored encoder, Lean formal model with 64 kernel-checked theorems, 4-way differential harness (20,197 streams, 0 findings), fuzz targets, size reports, and CLI all complete and passing CI gates.
