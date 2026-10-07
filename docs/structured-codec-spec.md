# B: DSC1 byte-exact structured codec specification

Status: experimental prototype v1, not ZIP/DEFLATE framing and not a released
format. [Plan](new-methods-plan.md), [protocol](../scripts/new_methods_protocol.json).
Implement an independent reference and vectors before relying on Rust roundtrip.

## Purpose and scope

Separate repeated exact quoted lexemes, literal bytes, operation tags and
canonical unsigned integers into streams with different distributions. Use
the sealed baseline DEFLATE backend initially. This tests a reversible transform
and framing, not a newly invented entropy coder. No JSON parsing/reserialization,
schema normalization, hidden external dictionary or discarded formatting is
allowed. Input is arbitrary bytes, including malformed JSON and invalid UTF-8.

Only experimental `structured-codec` depends on local `deflate-core`. It uses
`no_std + alloc` and forbids unsafe code. Reference libraries/tools are outside
that crate. Runtime heuristics are untrusted proposals: before emission,
reconstruct and compare the complete proposed chunk to original bytes, inside
the encoder timer; reject an invalid proposal and use an ordinary alternative.

## Outer frame: little-endian fields

Fixed 24-byte header:

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | ASCII `DSC1` |
| 4 | 1 | Version 1 |
| 5 | 1 | Chunk log2: 16 or 18 |
| 6 | 2 | Reserved zero |
| 8 | 8 | Total decoded byte count |
| 16 | 4 | Chunk count |
| 20 | 4 | CRC-32/ISO-HDLC of all original bytes, as existing core CRC32 |

Chunk count is zero for empty input; otherwise exactly ceil(total/2^chunk_log2).
Every nonfinal chunk has that full raw size; the final size is 1..2^chunk_log2.
Empty frame CRC is zero. Chunks are independent; no dictionary/history is shared
across chunks. Append no bytes after the last chunk. No concatenated-frame
decoding in v1; concatenation is an error, not silently accepted trailing data.

Each chunk has a 16-byte header followed by its declared payload:

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 1 | Mode 0 raw; 1 standalone raw-DEFLATE; 2 split transform |
| 1 | 1 | Flags zero |
| 2 | 2 | Reserved zero |
| 4 | 4 | Raw byte count |
| 8 | 4 | Payload byte count |
| 12 | 4 | CRC32 of this decoded chunk |

Mode 0 payload is exactly raw_count bytes. Mode 1 is one complete standalone
RFC 1951 stream, decoded to exactly raw_count bytes. Compressed-member handling
must check final member consumption (only final-byte unused bits are permitted).
Existing `inflate_with_limit` returns output without consumption; do not assume
it satisfies this additional contract. A strict research helper/model must
track consumption, without altering the existing decoder's suffix semantics.

All counted bytes, dictionaries, varints, CRC, substream headers and padding
are included in packed-size comparisons. Selecting raw/DEFLATE instead of the
transform still pays DSC1 header overhead; external baselines do not receive an
unreported DSC1 wrapper. Report framing-only overhead separately as a diagnosis.

## Split payload and substreams

Mode 2 starts with four 12-byte descriptors, in order: dictionary, operations,
literals, numbers. Each descriptor is raw_count:u32, stored_count:u32,
storage:u8 (0 verbatim, 1 standalone raw-DEFLATE), then three reserved zero bytes.
Exactly four stored payloads follow in the same order. Their sizes plus 48 equal
the chunk payload size. A zero-length substream uses storage0/counts0.
Storage0 requires equal raw/stored counts. Storage1 must consume one complete
member and decode exactly raw_count bytes. No nested transform or recursive frame.

For a chunk of n raw bytes: dictionary plaintext ≤65536 bytes; each other
plaintext ≤4n; their combined plaintext ≤8n+65536. Stored lengths may not exceed
these respective plaintext caps plus 64 bytes; the total payload is bounded
by 8n+65536+304 (48 descriptors +4×64 slack). Reject declarations violating a
bound before allocation or decompressing. These generous wire limits allow
handmade expansion witnesses; the normal encoder selects only smaller output.

### Canonical ULEB128

Varints encode u64 with seven low payload bits per byte and bit7 continuation.
Zero is `00`. At most ten bytes, tenth payload bit ≤1, no redundant top zero
groups, no continuation on byte10. Reject overflow, truncated and nonminimal
encodings. Lengths/IDs are additionally checked against their field budgets
before conversion to host usize. Never allocate directly from an unchecked count.

### Dictionary plaintext

ULEB128 entry count (0..256), followed by length:ULEB128 and exact bytes per
entry. Each entry is 1..256 bytes; entries are unique; consume the entire stream.
An empty dictionary is the single byte `00`, not a zero-length stream.
Canonical encoder entries are eligible quoted byte lexemes observed at least
three times. For lexeme length l and occurrence count c, rank descending by
the conservative score c×(l−3)−l−ULEB_length(l); retain only positive scores,
breaking ties by first occurrence then bytewise lexicographic order. The three
bytes budget one opcode plus the largest possible two-byte dictionary ID.
Assign IDs in this order, selecting up to 256 entries while the entire serialized
dictionary (including the entry-count varint) stays within 65536 bytes.
Serialized dictionary bytes, its scan/table cost and actual rebuilt stream costs
are fully charged. Estimated savings never decide final whole-frame output.

### Operation plaintext

Sequence of operations until its exact end:

| Opcode | Following bytes | Action |
| --- | --- | --- |
| 0 | ULEB128 positive length | Consume that many literal-stream bytes and append |
| 1 | ULEB128 dictionary ID | Append the exact dictionary entry |
| 2 | None | Read a numbers-stream ULEB128 u64; append canonical decimal ASCII |
| 3 | None | Read zigzag delta; add to previous numeric value, append canonical decimal |

Other opcodes are errors. At finish, exactly n output bytes must have been
produced and literal/numbers streams must be exhausted. Check remaining output
budget before each append. Every operation emits ≥1 byte, bounding operation
count by n; decoded stream sizes also bound parsing work. Dictionary references
never expand recursively. Zero-length literal runs are invalid.

Numeric state initially has no value; opcode3 requires one. Both opcode2 and
opcode3 replace that state. Canonical decimal is `0` or `[1-9][0-9]*`, within
u64, with no sign, whitespace, decimal point or exponent. All other spellings
remain byte-exact literals/dictionary entries: `-0`, `0007`, `1.0`, `1e3`,
very large integers and signed forms are never silently normalized.

For signed delta d in i64, zigzag is 2d for d≥0, or -2d-1 otherwise, computed
with checked/wide arithmetic. Inverse is z/2 for even z, -(z/2)-1 for odd z.
Add in a wide integer domain, requiring the result to lie in 0..2^64-1.
Encoder uses opcode3 only when previous value exists, difference fits i64 and
its canonical varint is strictly shorter than absolute; ties use opcode2.
No wrapping, saturating or floating-point arithmetic defines numeric decoding.

## Encoder scanner and deterministic choice

Scan each chunk as bytes. A quoted lexeme begins at byte `22`, ends at its
first unescaped `22`; a backslash consumes its following byte without decoding
or validating an escape. Unterminated strings and boundary-spanning fragments
stay literal. `keys` mode considers a closed quoted lexeme only when the next
non-whitespace byte in this chunk is `:`; `all-quoted` considers every closed
quoted lexeme; `off` builds no dictionary. Whitespace is ASCII space/tab/CR/LF.
This does not claim JSON validity. Cursor advance partitions every input byte
exactly once, preserving raw order and duplicated keys.
In `keys` mode, only key-position quoted spans may become dictionary references;
an identical value-position lexeme stays literal. `all-quoted` permits both.

With numeric mode enabled, outside quoted lexemes a digit, `+`, `-` or `.` starts
a maximal span of bytes in `0123456789+-eE.`. Transform only spans consisting
entirely of canonical unsigned digits, bounded by 20 digits and u64; spans with
an immediately adjacent ASCII letter or underscore remain literal too. Thus
`-0`, `0007`, `1.0`, `1e3` and overflowing integers remain literal. Other bytes
advance individually. Dictionary substitution has priority, then numbers, then
coalesced literal runs. This grammar may transform digit runs in non-JSON input
when reconstruction is exact; no semantics or schema is inferred by the decoder.

For each plaintext substream, actually build baseline Balanced raw-DEFLATE;
choose compressed storage only if its bytes are strictly fewer than plaintext.
Then construct/check a complete transform candidate, construct original-chunk
Balanced DEFLATE and raw alternatives, and compare complete payload sizes.
Smallest wins; ties: raw, ordinary DEFLATE, transform. All discarded passes,
dictionary computation and reconstruction checks occur inside encode timing.
This ensures only a measured within-DSC1 improvement, not superiority over zstd
or another framing. Whole-frame CRC construction is also charged.

Roster: chunk log2 16/18 × dictionary off/keys/all-quoted × numeric off/delta =12.
Numbers always support absolute fallback. The untransformed DSC1 control uses
the same chunk setting and raw/DEFLATE selection without transform scanning.

## Decoder limits, errors and verification

Caller supplies output limit; convenience default is 64 MiB. Reject declared
total above the limit before allocation. Process one chunk at a time; retained
temporary memory is bounded by one chunk's four plaintext streams, dictionary
and output under their declared caps. Count/check compressed input consumption,
not just CRC. CRC agreement is integrity evidence, not collision-freedom proof.

Stable error categories: badMagic, unsupportedVersion, badFlags, badChunkCount,
invalidLength, unexpectedEof, noncanonicalVarint, integerOverflow, badStorage,
deflateError, trailingData, duplicateDictionary, badDictionaryId, badOpcode,
missingNumericBase, unusedSubstream, outputLimit, checksumMismatch. Parse header
and sizes before content; preserve first encountered structural/decode error.
Reference and Rust must agree on normative vectors and explicitly shared error
precedence; do not promise every error equivalence before model agreement.

Independent vectors include empty/raw, dictionary keys/values, whitespace and
escape spellings, invalid UTF-8, absolute/delta extrema, duplicate keys, chunk
cuts inside escapes/numbers, all missing/trailing/overlong lengths, false CRC,
unknown IDs/opcodes, missing numeric base and over/underflow. Successful decoding
is byte equality to the original, not semantic JSON equality.

Lean model stages: pure operation expansion/invariants and integer rendering;
checked proposals reconstruct original; independent-stream composition and
bounded exact member decoding; complete frame encode/decode roundtrip.
Name assumptions about the embedded DEFLATE model and byte consumption. Existing
DEFLATE theorems do not prove this new format. Rust correspondence remains finite
tests until a refinement bridge is actually provided. No B production promotion
before its applicable frame/model and numeric/resource/CI gates pass.
