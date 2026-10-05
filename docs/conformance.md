# Conformance matrix (spec §13)

"Formally covered" means a named theorem in `spec/Deflate/Properties.lean`
covers the feature *in the Lean model*. It never means the Rust code is
proved, and it never counts a theorem from another project.

| Feature | Implemented | Tested | Formally covered |
| --- | --- | --- | --- |
| Bit reader (LSB-first, EOF) | yes | yes | yes |
| Stored blocks | no | no | no |
| Fixed Huffman | no | no | no |
| Dynamic Huffman | no | no | no |
| Multi-block streams | no | no | no |
| Overlapping back-reference | no | no | no |
| Malformed input rejection | no | no | no |
| Output limit | no | no | no |
| Encoder validity | no | no | no |
| Round trip | no | no | no |
