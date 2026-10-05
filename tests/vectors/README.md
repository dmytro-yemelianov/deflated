# Test Vectors

This directory contains test vector pairs for the RFC 1951 DEFLATE decoder and differential test harness.

## Organization and Naming

Each test case consists of two files sharing a base name:

- `<name>.deflate`: raw RFC 1951 bitstream (no zlib or gzip container headers/footers).
- `<name>.raw`: expected decompressed payload.

### Standard Test Suites

- **Stored blocks (BTYPE = 00):**
  - `stored_level0.deflate`, `stored_level0.raw`: uncompressed blocks generated via zlib level 0 to exercise block framing, byte-alignment discarding up to 7 pad bits, and `LEN`/`NLEN` one's complement verification.
- **Dynamic Huffman blocks (BTYPE = 10):**
  - `dynamic_hello.deflate`, `dynamic_hello.raw`: dynamic Huffman stream exercising HLIT/HDIST/HCLEN header parsing, code length alphabet decoding, literal/length tree decoding, and back-reference copying.
  - `dynamic_nodist.deflate`, `dynamic_nodist.raw`: dynamic Huffman stream with no back-references (highly varied short inputs where distance tree has 0 or 1 symbol, exercising degenerate distance tree handling per ADR 0004).
- **Regression and minimized cases:**
  - Additional vectors minimized from differential fuzzing discoveries or edge-case investigations.

## Usage and References

- **Rust test suite:** Integration tests embed these vectors directly via `include_bytes!("../../../tests/vectors/<name>.<ext>")`, ensuring tests execute reproducibly without runtime file dependencies or network access.
- **Differential oracle harness:** Python oracles (`oracles/differential.py`) scan this directory as a golden baseline across zlib, the Lean model, and `lean-zip`.
- **Fuzzing corpus:** `fuzz/corpus/inflate/` is seeded from all `.deflate` files in this directory.

## Generation and Provenance

Vectors are generated deterministically using reference tools (such as zlib reference encoders via Python snippets documented in test plans) and committed to the repository. They are never generated during the build.
