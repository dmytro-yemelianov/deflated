# Architecture of verified-deflate

This document outlines the system architecture of `verified-deflate`, describing the pipeline of modules, the module-by-module mirroring between Rust and Lean 4, and the oracle protocol connecting them.

## Dual Implementation Strategy

Following the architecture established in `maked`, `verified-deflate` builds two independent artifacts side-by-side:

1. **Rust Engine (`crates/deflate-core`, `crates/vdeflate`)**: A production-oriented `#![no_std]` Rust implementation with zero dependencies and `#![forbid(unsafe_code)]`.
2. **Lean 4 Reference Model (`spec/Deflate/`)**: An executable formal specification in Lean 4 with kernel-checked theorems proving key mathematical properties (P1–P7, P10–P12, including the compressing encoder's `decode_compress`) without `sorry`, `admit`, or `native_decide`.
3. **Differential Bridge (`oracles/`, `fuzz/`)**: Following ADR 0003, no automatic refinement proof connects the Rust and Lean implementations; instead, an N-way differential harness (testing Rust, Lean, zlib, and `lean-zip`) and continuous fuzzers provide empirical correspondence evidence over tens of thousands of streams.

## Module Mirroring

The Lean reference model in `spec/Deflate/` mirrors `crates/deflate-core/src/` file for file:

| Subsystem | Rust Source (`crates/deflate-core/src/`) | Lean 4 Model (`spec/Deflate/`) | Proved Invariants |
| --- | --- | --- | --- |
| Types & Errors | [crates/deflate-core/src/error.rs](crates/deflate-core/src/error.rs) | [spec/Deflate/Basic.lean](spec/Deflate/Basic.lean) | Deterministic error kinds match name-for-name |
| Bit Reader | [crates/deflate-core/src/bitstream.rs](crates/deflate-core/src/bitstream.rs) | [spec/Deflate/Bitstream.lean](spec/Deflate/Bitstream.lean) | P1: LSB-first reading, monotonicity, bounds, byte alignment idempotence |
| Huffman Tables | [crates/deflate-core/src/huffman.rs](crates/deflate-core/src/huffman.rs) | [spec/Deflate/Huffman.lean](spec/Deflate/Huffman.lean) | P2: Kraft completeness, degenerate distance tree acceptance (ADR 0004), decoded symbol range |
| Huffman decode table | [crates/deflate-core/src/huffman.rs](crates/deflate-core/src/huffman.rs) (ADR 0005) | [spec/Deflate/HuffmanTable.lean](spec/Deflate/HuffmanTable.lean) | P2: table fast path equals the canonical decode (`decodeSymFast_eq`) |
| LZ77 Tables & Copy | [crates/deflate-core/src/lz77.rs](crates/deflate-core/src/lz77.rs) | [spec/Deflate/LZ77.lean](spec/Deflate/LZ77.lean) | P6, P7: Length/distance symbol bounds, strictly positive copy progress, overlap semantics |
| Block Headers & Bodies | [crates/deflate-core/src/block.rs](crates/deflate-core/src/block.rs) | [spec/Deflate/Block.lean](spec/Deflate/Block.lean) | P3, P4, P5: Header parsing, stored block len/nlen check, Huffman block body loop monotonicity, dynamic tree alphabet permutation |
| Decoder State Machine | [crates/deflate-core/src/inflate.rs](crates/deflate-core/src/inflate.rs) | [spec/Deflate/Decode.lean](spec/Deflate/Decode.lean) | P12: Decoder determinism, output limit compliance |
| Stored Encoder | [crates/deflate-core/src/deflate.rs](crates/deflate-core/src/deflate.rs) | [spec/Deflate/Encode.lean](spec/Deflate/Encode.lean) | P10, P11: Minimal valid RFC 1951 stream generation, round-trip correctness (`decode_encodeStored`) |
| Compressing Encoder | [matcher.rs](crates/deflate-core/src/matcher.rs), [tokens.rs](crates/deflate-core/src/tokens.rs), [bitwriter.rs](crates/deflate-core/src/bitwriter.rs), [encode_fixed.rs](crates/deflate-core/src/encode_fixed.rs), [compress.rs](crates/deflate-core/src/compress.rs) | [Match.lean](spec/Deflate/Match.lean), [Tokens.lean](spec/Deflate/Tokens.lean), [BitWriter.lean](spec/Deflate/BitWriter.lean), [EncodeFixed.lean](spec/Deflate/EncodeFixed.lean), [Compress.lean](spec/Deflate/Compress.lean) | P11: `decode_compress` for every finder and input; the matcher is untrusted and re-checked by `accept` (ADR 0006) |

The headline theorems are verified in [spec/Deflate/Properties.lean](spec/Deflate/Properties.lean) and registered in [spec/scripts/axioms.lean](spec/scripts/axioms.lean) to ensure only standard Lean axioms (`propext`, `Quot.sound`, `Classical.choice`) are relied upon.

## Oracle Protocol

The differential harness in [oracles/differential.py](oracles/differential.py) interacts with the binaries via a minimal text-line protocol over standard input and output:

- `LIMIT <N>`: sets output allocation budget (default `1 << 26` bytes).
- `DECODE <hex>`: decodes the hex-encoded DEFLATE bitstream, returning:
  - `OK <hex>` on success with decompressed payload.
  - `ERR <name>` on error, where error names match across Rust and Lean (`unexpectedEof`, `invalidBlockType`, `invalidStoredLength`, etc.).
- `ENCODE <hex>`: encodes the raw payload as stored blocks, returning:
  - `OK <hex>` on success.
- `EMIT <tok>*`: emits the token list as one fixed-Huffman block; `<tok>` is `l:HH` (literal byte, hex) or `m:LEN:DIST` (decimal). Replies `OK <hex>`.
- `DEFLATE <hex>`: compresses the payload; replies `OK <hex>`. The Lean driver's finder always returns `none`, so the harness checks round trips for this command rather than byte equality.

The differential harness exercises over 20,000 streams (zlib streams at levels 0–9, handmade boundary streams, truncations, and bit-flip mutations) and verifies agreement between Rust, Lean, zlib, and `lean-zip`.

## Verification Boundary

For a complete description of what is formally proved, what is evidenced by differential testing, and known gaps, refer to [docs/verification-boundary.md](docs/verification-boundary.md) and [docs/conformance.md](docs/conformance.md).
