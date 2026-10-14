# Verification boundary

What this document means by each claim, per spec §2. Read it before quoting
any correctness claim about this project.

## What is proved

Named theorems in `spec/Deflate/`, kernel-checked by Lean
4.30.0 with no `sorry`, no `admit` and no project-defined axiom. CI fails if
any of those appear, and fails if `#print axioms` shows a headline theorem
depending on `sorryAx` or `ofReduceBool`.

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
- **Full gzip framing (RFC 1952, Milestone M9).** `Deflate.Gzip` models a
  single member with the canonical ten-byte header, raw DEFLATE body and
  CRC32/ISIZE trailer. Optional headers, FHCRC and concatenated members are
  tested in Rust but are outside this initial Lean model. Its body uses the
  raw decoder, which tolerates unused trailing bytes; exact compressed-input
  consumption is not proved.
- **Full ZIP framing.** `Deflate.Zip` models canonical single-entry STORED
  archives with fixed metadata, no extra fields or comments, and checked
  field bounds excluding ZIP64 sentinels. The parser extracts the filename
  and payload from bytes and validates the complete container against its
  canonical encoding. General metadata, DEFLATE entries and data descriptors
  are tested in Rust but are outside this strict model. ZIP64 and encryption
  remain unsupported by Rust.
- **CRC collision freedom.** `Deflate.CRC32` computes reflected CRC-32 with
  polynomial `0xEDB88320` and checks the standard `123456789` vector by kernel
  evaluation. Integrity theorems establish matching checksums and sizes,
  not that CRC detects every corruption or uniquely identifies a payload.

## Proved theorems in the Lean model

The following headline theorems are kernel-checked with zero custom axioms.
The original core theorems are in `Properties.lean`; the additional modules
are named below.

- **P1 (Bit reader):** `byteAt_oob`, `readBits_pos`, `readBits_bytes`, `readBits_lt`, `readBits_eof`, `alignToByte_idem`.
- **P2 (Canonical Huffman):** `fixedLitLen_complete`, `fixedDist_complete`, `decodeSym_pos`, `decodeSym_bytes`, `decodeSym_in_range`.
- **P2 (Table-driven Huffman, ADR 0005):** `decodeSymFast_eq` (the table fast path equals `decodeSym` on every reader, results and errors alike), `decodeSym_local`, `buildTable_size`, `tableEntry_some`, `readBits_some`, `fixedLitLen_table_total`, `fixedDist_table_total`.
- **Table widths and lazy search:** `decodeSymFastAt_eq` covers every
  table width at most sixteen bits; `decodeSymFast_eq` specializes it to
  Rust's twelve-bit table, with a regression test guarding the shared
  constant. `accept_prefix` and `better_match_iff_threshold` justify
  checking only the prefix required to improve a lazy match. Rust token
  equality with a scalar search over each preset's candidate sets is checked
  by finite reference tests. The presets change heuristic search coverage;
  they preserve accepted-token validity rather than the previous token stream.
- **P3 (Block headers & stored blocks):** `readHeader_pos`, `readStored_aligned`, `readStored_consumes`, `readStored_rejects_bad_nlen`.
- **P4 (Huffman block body):** `decodeHuffBlock_monotone`, `decodeHuffBlock_within_limit`, `decodeHuffBlock_progress`.
- **P5 (Dynamic Huffman tables):** `clOrder_is_a_permutation`, `readDynamicCodes_valid`, `readDynamicCodes_pos`.
- **P6 & P7 (LZ77 back-references):** `copyBack_size`, `copyBack_overlap`, `copyBack_rejects`, `readLength_range`, `readDistance_range`.
- **P10 & P11 (Encoder validity and round trip):** `decode_encodeStored` (every input round-trips through the stored encoder, multi-block inputs over 65535 bytes included: `x.size ≤ limit → decode (encodeStored x) limit = .ok x`). This closed the stored-encoder P11 gap that earlier versions of this document recorded, with `encodeStored_empty` and `encodeStored_valid` as corollaries for empty input.
- **P11 (Compressed encoder, M7a/M7b):** `decode_compress` (the model compressor round-trips every input for every finder and every `lengthsFor`: `x.size ≤ limit → decode (compress find lengthsFor x) limit = .ok x`), resting on `decode_emitBlocks` (below), `decode_emitFixed` (a valid token list emitted as one fixed-Huffman block decodes to its expansion), `expand_compressTokens` and `compressTokens_valid` (the matcher re-checks every finder candidate, so tokenization is lossless and valid even for an adversarial finder).
- **P11 (Dynamic-Huffman encoder, M7b):** `decode_emitBlocks` (a valid token list emitted as blocks of at most 16384 tokens, each dynamic or fixed as the untrusted `lengthsFor` and `validLengths` decide, decodes to its expansion: `Valid ts → (expand ts).size ≤ limit → decode (emitBlocks lf ts) limit = .ok ⟨expand ts⟩`). It rests on `decodeSym_canonical` and `decodeSym_of_canonical_bits` (the decoder reads back every canonical code `canonicalCode` writes), `canonicalCode_fixedLit` and `canonicalCode_fixedDist`, `rleLengths_expand` and `rleLengths_inRange` (the code-length RLE), `readCodeLengths_go_emit`, `readCLLens_go_emit` and `readDynamicCodes_emitHeader` (the decoder reads back the header `emitHeader` writes), `validLengths_spec`, `huffLoop`, `readHeader_written`, `decodeBlock_emitFixedBlock`, `decodeBlock_emitDynamicBlock`, `decodeBlock_emitBlock` and `decodeFuelLoop_emitBlocksGo`. `emitBlocks_none` and `compress_none` show that with `lengthsFor := fun _ => none` and at most 16384 tokens the output is M7a's single fixed block. The length heuristic is not proved and need not be: every length set it returns is checked by `validLengths`, and a rejected one falls back to fixed.
- **P12 (Determinism & output limits):** `decode_deterministic`, `decode_within_limit`.
- **P8 (Fuel non-exhaustion, `Fuel.lean`):** `decode_never_exhausts` states
  `decode bs limit ≠ .error .fuelExhausted` for every byte array and every
  limit, including malformed streams. It rests on fuel bounds for
  `readCodeLengths.go`, `decodeHuffBlock` and `decodeFuelLoop`, without
  changing any decoder definition or fuel constant.
- **Custom splitting (`EncodeSplit.lean`):** `decode_emitSplitBlocks` and
  `decode_compressSplit` hold for every split callback and length heuristic.
  Callbacks see at most 16384 upcoming tokens; zero or oversized requests
  fall back to the default. The proofs preserve cross-block back-references,
  bound each chunk, and establish progress. `emitSplitBlocks_none` proves
  byte equality with the existing default emitter for every length heuristic.
- **Minimal gzip (`Gzip.lean`):** `NativeGzip.gunzip_gzip` gives a round trip
  for every finder, length heuristic and payload within the limit.
  `accepted_integrity`, `gunzip_within_limit`, `output_limit_rejection` and
  `checksum_mismatch_rejection` establish header/body/trailer validation,
  limits and rejection of a mismatching CRC field.
- **Canonical STORED ZIP (`Zip.lean`):** `NativeZip.unzip_zip` gives a round
  trip when `ValidFields` and the output limit hold. `zip_rejects_fields`
  rejects overflowing fields; `accepted_integrity`, `unzip_within_limit`,
  `output_limit_rejection` and `checksum_mismatch_rejection` cover the
  canonical container, metadata, checksum and output limit.

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
  0 findings, plus 160 requests with a one-symbol distance code of length
  0 to 15, where lengths 2 to 15 must give exactly the fixed block, since
  zlib rejects them, and every stream must decode under zlib; 0 findings)
  and `EMITBLOCKS` requests (fixed blocks only, up to 40000 tokens, 5
  requests, 0 findings). Its self-test, which checks that a corrupted Rust
  reply is detected, passes 10/10. A stream with several dynamic blocks is
  therefore checked by decoding only: no request compares its bytes with
  Lean's. It sends `DEFLATE`
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
- Custom Rust splitting (`deflate_with_split`, `SplitFor`) sees a bounded
  window of at most 16384 un-emitted tokens. Invalid counts fall back to the
  default. `emitSplitBlocks` mirrors these checks and proves round trips for
  every policy. Regression tests cover Rust custom boundaries and cross-block
  matches; no refinement proof connects the two implementations.
- `lean-zip` was not installed in the run that recorded these numbers, so no
  `lean-zip` result is claimed for the encoder.

## Explicit verification gaps

- **P8:** Closed by `decode_never_exhausts` in `Fuel.lean` for arbitrary
  finite inputs, not only encoder-produced streams.
- **Table-driven Huffman decoding (ADR 0005):** no gap in the Lean model: `decodeSymFast_eq` is the full equivalence, with no hypothesis on the code or the reader. The model's block decoder still calls `decodeSym`, and `decodeSymFast` is a separate definition proved equal to it. What is not proved is that the Rust table and peek mirror `buildTable` and `decodeSymFast`. Like the rest of the Rust, that rests on tests and the differential harness (ADR 0003), plus the unit test ADR 0005 asks for, which compares the Rust table against the by-evaluation construction.

## Status

The Lean model covers the raw decoder and stored/fixed/dynamic encoders,
general fuel non-exhaustion, checked custom splitting, minimal single-member
gzip and canonical single-entry STORED ZIP. Headline theorems are registered
in `spec/scripts/axioms.lean`. Rust correspondence remains test evidence:
the raw differential corpus has 20,197 streams and zero findings, with
focused framing checks in `oracles/framing.py`. The framing exclusions above
and the lack of a Rust refinement proof remain explicit boundaries.

## Library restart: Rust implementation changes (2026-10-14)

`inflate_into` reports byte consumption and replaces a caller-owned buffer;
`gunzip_into` reuses output storage and checks all members. Errors clear the
output. The one-shot wrappers retain their previous stream/error semantics.
Neither buffer lifecycle nor the new consumption result has a Lean refinement
proof. API regression tests cover suffixes, limits, truncation, recovery and
member/checksum validation; the existing differential suite still applies.

Fixed Huffman tables now share compile-time RFC tables rather than constructing
them for every block. Canonical reconstruction and literal table-evaluation
tests check every entry. Dynamic tables remain constructed from checked lengths.
CRC32 uses portable slicing by sixteen with an eight-byte/bytewise tail, checked against an independent bitwise
reference across offsets, tails and incremental chunk boundaries. These are
Rust test claims, not new Lean theorems. `no_std`, zero runtime dependencies and
`forbid(unsafe_code)` remain in force.

### Bulk token lookahead

The public symbol-table block decoder resolves complete table-hit tokens from a bounded
64-bit load. A successful load supplies at least 57 real bits; the current
tables and extras need at most 42 per token. Unused bits are retained across
tokens, refilled below 42, and discarded before scalar fallback. The reader
still commits each token's consumed bits immediately. Table misses, reserved
symbols and short input fall back without speculative consumption. The scalar
reference tests in `block_fast_tests.rs` compare exact errors, bit positions and
partial output using canonical Huffman decoding and independent byte copies.
The short-copy index is computed once rather than from the growing output on
every byte. Existing copy-reference, full differential and bounded fuzz checks
pass. These are finite Rust correspondence checks, not a Lean proof of this
lookahead implementation. Explicit tests also interleave buffered literal runs
with fifteen-bit codes and check every output limit through the run. See
[the v2 report](library-decode-v2-report.md) and
[the buffered decoder report](library-decode-v3-report.md).

### Dynamic-table preparation

The Rust Huffman builder now grows the table by copying each populated prefix
into its upper half before adding longer codes. Tests compare every lookup slot
with the canonical decoder for 2,000 complete trees and degenerate cases. The
dynamic-header parser uses a 316-byte local array after validating HLIT/HDIST;
reference tests compare its result and exact cursor with a growable parser using
canonical symbol decoding, including repeat overruns and truncations. Public
constructor tests also cover count overflow and symbol indices outside `u16`.
These are finite Rust checks; no new Lean refinement proof covers these memory
or construction changes. See [the v4 report](library-decode-v4-report.md).

### Reusable decoder state

`Decompressor` retains allocations for three dynamic Huffman tables and gzip
member scratch storage. Every header rebuilds its tables before use; a failed
rebuild is never decoded. Existing output is cleared before each stream and
after errors. Tests alternate table shapes (including empty/degenerate trees),
verify stale entries are overwritten without replacing table allocations, and
compare fresh/reused results across multiple blocks, mixed raw/gzip inputs,
truncations, limits, explicit release and error recovery. The `reuse` fuzz
target compares both API paths with state retained across inputs. This is
finite Rust evidence; retained allocation lifecycle has no Lean refinement
proof. See [the v5 report](library-decode-v5-report.md).

### Packed actions and initialized output batches

Whole-buffer APIs now use private packed-action tables with 12/9/7-bit roots
for literal-length, distance and code-length alphabets. Entries encode the
action type, base/literal value, symbol index, code length and total consumed
bits (including extra bits). Misses retain the canonical
walk, including partial consumption on malformed codes; they do not zero-pad
input. Tests compare all root entries and error cursors against the public
canonical API, including degenerate, long and reserved codes. This is not the
same representation as Lean's public 12-bit symbol table, so the existing Lean
table theorem is not a proof of the packed implementation.

The batch decoder initializes at most 8192 additional output bytes within the
decoded-length limit. A 264-byte guard covers every match: the word-copy path
writes at least forty bytes, then rounds longer matches to eight bytes, up to
264 for the maximum length of 258. A three-byte match can therefore write thirty-seven
padding bytes. Only the logical output prefix is valid history, and
speculative suffix bytes are truncated before return. Complete tokens advance a
local bit cursor; it is committed before a fallback, error or return. A long
code can resume in the same initialized region. Small fixed blocks retain the
compact public decoder. Tests compare both paths' exact results, positions and
partial output across copy, batch, dispatch and limit boundaries.
The next packed action can be read before copying a match. This lookup stays
inside the table and consumes no input; a refill replaces it before use when
the remaining real bits cannot support a full token. Exhaustive copy-length
tests compare the logical output with bytewise history expansion. V9 expresses
the copy source and destination relative to one checked region; the ARM64
compiler unrolls the continuation. Distances below eight use a separate function with
the same checked fill/prefix-expansion semantics; no path is marked unreachable
or allowed to read uninitialized history.

The v8 batch loop derives its logical bit position as `next_byte * 8 - available`.
It appends real input bytes into the bit buffer, advances the byte cursor and
retains 56–63 counted bits without consuming a token. Any overlapping high bits
are from the same input bytes. No input padding is assumed. The token guard also
covers three maximum-width literal codes, which may share one iteration. Tests
compare exact scalar positions across all initial alignments, each truncation
of short literal runs, every group-ending position and output limits. Every
possible extra length/distance value is checked independently against the RFC
base/extra arrays. These are additional finite checks, not a proof of the refill
or grouped decoder.

The wider portable CRC loop is checked against the independent bitwise reference
across tails, offsets, empty updates and incremental chunks. The implementation
remains safe `no_std` Rust with no runtime dependencies. Full differential and
bounded fuzz checks provide finite correspondence evidence; no Rust refinement
proof or new Lean theorem is claimed. See the [v6](library-decode-v6-report.md)
[v7](library-decode-v7-report.md) and [v8](library-decode-v8-report.md) reports.

### Gzip header consumption without metadata allocation

V10's decompression path checks byte-aligned gzip headers without constructing
owned metadata. A valid minimal ten-byte header commits one cursor advance;
optional fields are scanned as bounded byte slices. Header CRC is computed only
when FHCRC is present, and is still validated. Incomplete, invalid, checksum-bad
or unaligned headers enter the unchanged public `read_gzip_header` from the
original reader position, preserving its error precedence and partial cursor.
The public metadata API, payload CRC, output limits, member isolation and
zero-padding rules remain unchanged.

Tests compare results and exact positions with that public parser for all 32
valid flag combinations, alignments, truncations, header mutations, maximum
extra-field length, long strings and readers positioned past the end. The
`gzip_header` fuzz target independently uses the public parser's accepted
boundary to frame an empty DEFLATE payload, and compares header rejection
before decoding. Optional gzip headers remain outside the Lean framing model;
these are finite Rust correspondence checks, not a new refinement proof.
