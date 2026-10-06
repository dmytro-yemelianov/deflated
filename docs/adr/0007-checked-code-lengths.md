# ADR 0007: Code lengths are checked, never trusted

**Status:** accepted, implemented (Lean and Rust) · **Date:** 2026-10-06

## Context

M7b adds dynamic-Huffman blocks to the encoder. Choosing the code lengths
(`build_lengths`: a length-limited prefix code from symbol frequencies, plus
the run-length encoding of the length table and the code-length code) is
the part with freedom in it, and the fiddly part: package-merge or heap
construction, depth limiting to 15 (7 for the code-length code), tie
breaking. A round-trip proof that depended on one construction would break
the first time it was tuned, exactly as ADR 0006 argued for the matcher.

## Decision

- The length heuristic is **untrusted**. In Lean it is `lengthsFor`, a
  function of the tokens returning `Option (lit, dist, cl)` length arrays
  (`spec/Deflate/EncodeDynamic.lean`). In Rust it is `lengths_for`
  (`encode_dynamic.rs`) over `build_lengths` (`huffman_build.rs`).
- Every result is **checked by `validLengths` / `valid_lengths`**: sizes in
  range; lit and dist lengths at most 15, code-length lengths at most 7; the
  literal/length and code-length codes complete; the distance code
  acceptable under ADR 0004 **and** either complete or with no length above
  1; every symbol the block uses (literals, 256,
  length and distance symbols, and every code-length symbol its RLE uses)
  has a nonzero length.
- **The distance rule is zlib's, not the decoder's.** Our decoder (ADR
  0004, `isValidDistance`) reads a lone distance code of any length, but
  zlib accepts an incomplete distance code only when no length exceeds 1
  (inftrees.c rejects `left > 0 && max != 1`), i.e. one used symbol of
  length 1 or none at all. The check demands that, so a stream that passes
  it is one zlib reads too (M7b final review, finding 2). The stronger
  check only adds a conjunct, so `decode_emitBlocks` is unchanged.
- **Fixed fallback.** A block is dynamic only if the lengths are `some`,
  valid, and `dynBits < fixedBits`; otherwise the block is fixed. A heuristic
  that fails, declines or lies costs ratio, never correctness.
- `decode_compress` holds for every finder, every `lengthsFor` and every
  input, through `decode_emitBlocks`, `readDynamicCodes_emitHeader`,
  `rleLengths_expand` and `decodeSym_canonical`. The heuristic itself is
  unproved. `emitBlocks_none` and `compress_none` show that
  `lengthsFor := fun _ => none` gives M7a's output.
- **Default block size is 16384 tokens.** Custom splitting is checked and
  covered by `EncodeSplit.lean`: invalid counts fall back to the default,
  chunks are nonempty unless the input is empty, and only the final block
  sets BFINAL. `decode_compressSplit` holds for every checked `splitFor`.
  Rust supplies a bounded token window; Lean supplies the remaining list.
  The proof covers correctness for each policy, while byte equality
  requires matching policy decisions (see `docs/verification-boundary.md`).
- **The code-length code's lengths are passed explicitly.** The CL code is
  also built by a heuristic, so for Rust and Lean to emit identical bytes
  the oracle command carries all three arrays: `EMITDYN <lit> <dist> <cl>
  <tok>*`, one hex digit per length, CL lengths indexed by CL symbol. It
  emits dynamic whenever the lengths are valid, with no size comparison, so
  the dynamic path is always exercised. Rust-only `LENGTHS <tok>*` reports
  the lengths `deflate` would pick, so the harness can feed them to both.

## Why the check is cheap

`valid_lengths` is a Kraft sum and a pass over the used symbols, linear in
the alphabet sizes only: Rust derives the used set from the block's
frequency counts, which the heuristic and both bit counts (`Σ freq·len`
plus extra bits) share, so each block's tokens are walked once to analyse
and once to emit.

## Alternatives considered

- **Prove the heuristic.** A length-limited prefix-code construction proof
  is large and would be reopened by every tuning change. The check gives the
  same guarantee in a few lines.
- **Let Lean build the CL lengths itself.** Then both sides would need the
  same heuristic, and byte equality would depend on mirroring it exactly.
  Passing them explicitly keeps the differential test about the emitter.
- **Fixed blocks only.** Provable and shipped in M7a, but its ratio on text
  is well behind miniz_oxide level 6.

## Consequences

- Rust and Lean are linked by mirroring plus differential testing, as for
  M7a (ADR 0003): `canonicalCode`/`canonical_codes`, `rleLengths`/
  `rle_lengths`, `validLengths`/`valid_lengths`, `emitDynamicBlock`/
  `emit_dynamic_block`, `emitBlocks`/`emit_blocks`. `EMITDYN` compares them
  byte for byte; `DEFLATE` checks that Rust, Lean and zlib decode every
  produced stream. The Lean `DEFLATE` finder still returns `none`.
- The `dynamic_lengths` fuzz target checks that `build_lengths` yields a
  set the decoder accepts for arbitrary frequencies.
- A better length heuristic is a Rust-only change plus a differential
  re-run; the Lean theorems stand, because only `lengthsFor` is a
  parameter. A block splitter is also a checked parameter in `EncodeSplit.lean`.
- Dynamic multi-block streams are compared **by decoding only**. `EMITDYN`
  checks one dynamic block byte for byte, and `EMITBLOCKS` checks the
  multi-block cutting byte for byte with fixed blocks (`lengthsFor =
  none`). A Rust stream with several dynamic blocks is never compared with
  Lean's bytes; `DEFLATE`, the Rust tests and the fuzz target check that
  Rust, Lean, zlib and `miniz_oxide` decode it to the input.
