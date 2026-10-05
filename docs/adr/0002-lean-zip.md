# ADR 0002: The role of lean-zip

**Status:** accepted · **Date:** 2026-10-05

## Context

Spec §14 requires inspecting `lean-zip` before committing to architecture.
It is a pure-Lean 4 zlib with a DEFLATE encoder and decoder and a
kernel-checked theorem that decompressing `compress x` returns `x`.

Two facts decide the role:

1. That round-trip theorem is **exactly** the property spec §2 names as
   necessary but not sufficient. Two mutually compatible implementations can
   round-trip while both violating RFC 1951.
2. The theorem is about `lean-zip`'s own Lean code. Spec §13 forbids marking
   a feature formally covered because a different implementation has a
   proof.

## Decision

`lean-zip` is a **differential oracle and a definition reference**, not a
dependency and not a source of coverage.

- We write our own small model in `spec/Deflate/`, shaped to mirror the Rust
  state machine so the two can be diffed byte for byte.
- `lean-zip` joins `zlib` as an independent party in `oracles/differential.py`.
  It is valuable there precisely because it is an *independent reading of
  RFC 1951 by a different author*, which `zlib` is not: `zlib` is the de
  facto definition, so agreeing with it proves compatibility, not conformance.
- Where our reading of an ambiguous RFC passage differs from `lean-zip`'s,
  the difference is recorded in this file rather than silently resolved.

## Recorded facts

- **Revision:** `2f7a63f38195bc667a926881b55d10c9f8a88eeb`
- **License:** Apache License, Version 2.0 (January 2004, http://www.apache.org/licenses/, Copyright 2026 Kim Morrison)
- **Lean toolchain:** `leanprover/lean4:v4.35.0-rc2` (differs from project `leanprover/lean4:v4.30.0`; tolerated because `lean-zip` runs as an external oracle binary)
- **Builds on this machine:** yes, 4m 09s wall time
- **Definition map:**

| RFC 1951 Feature | lean-zip Definition | Description & Notes |
| --- | --- | --- |
| Bit reader (LSB-first, EOF) | `ZipCommon.BitReader` / `Zip.Native.Inflate.readBitsFast` | Bit reader consuming LSB-first bits from byte streams, with EOF check (`pos ≥ br.data.size`) |
| Stored blocks | `Zip.Native.Inflate.decodeStored` | RFC 1951 §3.2.4 uncompressed block decoder verifying `len ^^^ nlen == 0xFFFF` and copying `len` bytes |
| Fixed Huffman | `Zip.Native.Inflate.decodeHuffmanFast` / `fixedLitLengths` / `fixedDistLengths` | RFC 1951 §3.2.6 fixed Huffman code tables (`Zip.Spec.DeflateFixedTables`) and fast table decoder |
| Dynamic Huffman | `Zip.Native.Inflate.decodeDynamicTrees` | RFC 1951 §3.2.7 dynamic code header decoder (HLIT, HDIST, HCLEN, code-length alphabet, and tree reconstruction) |
| Multi-block streams | `Zip.Native.Inflate.inflateLoop` / `InflateBuf.inflateLoopBuf` | Block sequence loop processing headers and blocks until `bfinal == 1` is observed |
| Overlapping back-reference | `Zip.Native.Inflate.copyLoop` (`Zip.Native.ExtendWithin`, `c/extend_within_ffi.c`) | Self-overlapping match copying for LZ77 distance back-references in decompression |
| Malformed input rejection | `Zip.Native.HuffTree.fromLengths`, `decodeStored`, `decodeDynamicTrees`, `inflateLoop` | Rejects oversubscribed trees (`kraft > 2^maxBits`), invalid block types (BTYPE=3), length check mismatch, distance exceeding output |
| Round trip | `Zip.Spec.ZlibCorrect.zlib_decompressSingle_compress` | Verified kernel-checked theorem that decompressing compressed stream recovers original byte array |

## Semantic differences found

- Incomplete Huffman trees: `lean-zip` (`HuffTree.fromLengths`) accepts under-subscribed code length assignments during tree construction, rejecting missing codes only when encountered in the bitstream, whereas strict RFC 1951 interpretation distinguishes complete trees and degenerate single-symbol distance trees (ADR 0004).

## Consequences

`docs/conformance.md`'s "Formally covered" column counts only theorems in
`spec/Deflate/Properties.lean`. The harness reports `lean-zip` disagreements
as findings to investigate, not as test failures, until a disagreement is
traced to a defect on one side.
