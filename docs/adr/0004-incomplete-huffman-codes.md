# ADR 0004: Incomplete and degenerate Huffman codes

**Status:** accepted · **Date:** 2026-10-05

## Context

RFC 1951 §3.2.2 describes how to build a canonical code from lengths. It does
not say what a decoder must do with a length set that is *incomplete* — one
whose Kraft sum is below 2^15, leaving bit patterns unassigned. Over-
subscription (sum above 2^15) is unambiguously malformed.

The case matters because real encoders emit it. A block with no
back-references has nothing to say in the distance alphabet, so zlib writes a
distance code with zero or one symbol. Rejecting those breaks interoperability
with the dominant encoder; accepting every incomplete code means a corrupt
tree decodes to arbitrary symbols instead of being reported.

## Decision

- Over-subscribed (`kraft > 2^15`): always `InvalidHuffmanTree`.
- Complete (`kraft == 2^15`): always accepted.
- Incomplete (`kraft < 2^15`): accepted only when at most one symbol has a
  non-zero length, and only where the caller passes `Completeness::AllowDegenerate`.
  The literal/length tree and the code-length tree always pass
  `Completeness::Complete`; only the distance tree passes `AllowDegenerate`.

This is the decoder's rule, and it is more lenient than zlib's: zlib
accepts an incomplete distance code only when no length exceeds 1 (one
symbol of length 1, or none), so it rejects a lone distance code of length
2..15 that we read. Leniency is fine for a decoder; the encoder's check
(`valid_lengths` / `validLengths`, ADR 0007) demands zlib's stricter rule.
`lean-zip`'s reading is recorded in ADR 0002; where it
differs, the difference is noted there and the harness reports it as a
finding rather than a failure.

## Consequences

A single-symbol distance code decodes that symbol after reading its one bit.
If such a block then contains a length symbol, the distance decode either
yields the one defined symbol or returns `InvalidCode`; it never reads
uninitialized table entries.
