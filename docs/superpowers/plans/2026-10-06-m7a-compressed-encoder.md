# M7a Compressed Encoder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **Token-efficient format (user requirement).** This plan does not include
> code bodies. Each task gives exact names, signatures, theorem statements and
> acceptance checks; the implementer writes the code. Return a terse result:
> files changed, gate output tails, any deviation from a name in this plan.
> Run only your own task's checks. The expensive gates (differential, perf,
> size, fuzz) run once, in Tasks 11–12.

**Goal:** `vdeflate -c` compresses (LZ77 + fixed Huffman, stored fallback),
with a Lean theorem that the model compressor round-trips every input.

**Architecture:** A matcher that checks every candidate turns input into
tokens. It is proved correct for any candidate finder. A fixed-Huffman emitter
is proved to decode back to `expand tokens`. The compressor picks the smaller
of fixed and stored. Rust mirrors each Lean unit; differential testing ties
them (ADR 0003).

**Tech Stack:** Lean 4 v4.30.0 (lake), Rust 1.88 edition 2024, Python 3 oracles.

**Spec:** `docs/superpowers/specs/2026-10-05-m7a-compressed-encoder-design.md`. Read §3 for your component before starting.

## Global Constraints

- Lean: no `sorry`, `admit`, `native_decide` or new axioms. `decide +kernel`
  is allowed. Headline theorems go in `spec/scripts/axioms.lean`. Gate:
  `make test-lean`.
- Rust core: `#![no_std]`, `#![forbid(unsafe_code)]`, zero dependencies, no
  `std` in `crates/deflate-core/src`, no panicking paths (no `[]` indexing,
  `unwrap`, `expect`, failing slices or overflowing arithmetic; use `.get()`
  and checked ops).
- Rust gates per task: `cargo fmt --all --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`, and
  `cargo test -p deflate-core` (plus `-p vdeflate` when CLI files change).
- Existing theorems, `inflate`, `deflate_stored` and the `ENCODE` oracle
  command must not change behaviour.
- Never run `--record` scripts or `scripts/size_report.sh` except in Task 12.
- Commit only your task's paths: `git commit -- <paths>`. If you hit
  `index.lock`, retry; the Lean and Rust tracks run in parallel. End messages
  with the session's Co-Authored-By / Claude-Session lines.
- Comments: short, say why, name the Lean counterpart.

## Review Focus

1. **Empty input.** `deflate(&[])` and `compress find ⟨#[]⟩` return a valid
   stream that decodes to empty. Test owner: Tasks 9 and 8.
2. **Stored chunk boundaries.** Inputs of 65535, 65536 and 131071 bytes
   round-trip, and the fixed/stored choice is right on both sides. Test owner:
   Task 9. Lean covers it by `decode_encodeStored`.
3. **Match bounds.** `len` 258, `dist` 32768, `dist = i`, and an overlapping
   `dist < len` emit and decode correctly. Test owner: Tasks 7 and 9.
4. **Long runs.** Zeros and short-period repeats produce chains of 258-length
   matches at dist 1 that round-trip, with a bounded matcher time. Test owner:
   Task 9 (1 MiB zeros under 1 s in debug).
5. **Incompressible input.** Random bytes give stored output, at most
   `deflate_stored`'s size. Test owner: Task 9.

## Shared formats (used by Tasks 6, 7, 10, 11)

- **Fixed lit/len codes** (RFC 1951 §3.2.6): 0–143 is 8 bits from `0x30`,
  144–255 is 9 bits from `0x190`, 256–279 is 7 bits from `0`, 280–287 is 8
  bits from `0xC0`. Distance codes are 5 bits, code = symbol. Codes are
  written MSB-first, i.e. the bit-reversed code through the LSB-first writer.
- **Length symbol:** the largest `i` with `lengthBase[i] ≤ len` gives symbol
  `257 + i` and extra `len - lengthBase[i]` in `lengthExtra[i]` bits; 258
  uses symbol 285 with 0 extra bits. **Distance:** the largest `i` with
  `distBase[i] ≤ dist`, extra `dist - distBase[i]` in `distExtra[i]` bits.
- **`emitFixed` layout:** bits `1` (BFINAL), then `1` and `0` (BTYPE = 01 as
  `writeBits 1 2`), the tokens, symbol 256, then zero padding to a byte.
- **Oracle token syntax:** `EMIT <tok>*`, where `<tok>` is `l:HH` (a literal
  byte in hex) or `m:LEN:DIST` (decimal), space-separated. The reply is
  `OK <hex>`. `DEFLATE <hex>` replies `OK <hex>`. The Lean driver's finder for
  `DEFLATE` always returns `none`.

---

## Lean track (Tasks 1–5). Order: 1 and 2 in parallel, then 3, 4, 5.

### Task 1: Tokens and the matcher (Lean)

**Files:** Create `spec/Deflate/Tokens.lean` and `spec/Deflate/Match.lean`; modify `spec/Deflate.lean` (imports) and `spec/Deflate/Properties.lean` (new section).

**Produces:**
```lean
inductive Token | literal (b : UInt8) | «match» (len dist : Nat)
def expandStep (out : Array UInt8) : Token → Array UInt8   -- literal: push; match: copyGo dist out len
def expand (ts : List Token) : Array UInt8                 -- foldl expandStep #[]
def Token.valid (outSize : Nat) : Token → Prop             -- literal: True; match: 3 ≤ len ≤ 258 ∧ 1 ≤ dist ≤ 32768 ∧ dist ≤ outSize
def Valid : List Token → Prop                              -- every token valid against the size of expand of its prefix
abbrev Finder := Array UInt8 → Nat → Option (Nat × Nat)
def accept (x : Array UInt8) (i len dist : Nat) : Bool     -- the bounds and the byte-equality check from spec §3.2
def compressTokens (find : Finder) (x : Array UInt8) : List Token
theorem expand_compressTokens (find : Finder) (x : Array UInt8) : expand (compressTokens find x) = x
theorem compressTokens_valid (find : Finder) (x : Array UInt8) : Valid (compressTokens find x)
```

- [ ] Write the definitions. `compressTokens` recurses on `i` with `termination_by x.size - i`.
- [ ] Prove the generalized invariant first: the output of the tokens from `i` onward, appended to `x.extract 0 i`, is `x`. Then prove the two theorems and register them in `axioms.lean`.
- [ ] `make test-lean` passes. Commit.

### Task 2: Bit writer (Lean)

**Files:** Create `spec/Deflate/BitWriter.lean`; add a section to `Properties.lean`.

**Produces:**
```lean
structure BitWriter where bits : Array Bool                -- stream order; bytes made by `toBytes`
def BitWriter.writeBits (w : BitWriter) (v n : Nat) : BitWriter   -- LSB-first
def BitWriter.writeCode (w : BitWriter) (code len : Nat) : BitWriter  -- MSB-first
def BitWriter.toBytes (w : BitWriter) : ByteArray          -- zero-pads the last byte
theorem toBytes_bitAt (w) (i) (h : i < w.bits.size) : bitAt w.toBytes.data i = w.bits[i]
theorem readBits_written (w : BitWriter) (v n : Nat) (rest : BitWriter) (hv : v < 2 ^ n) :
  readBits ⟨((w.writeBits v n).bits ++ rest.bits |> BitWriter.mk).toBytes, w.bits.size⟩ n
    = some (v, ⟨_, w.bits.size + n⟩)
```

A list of bits keeps the proofs simple. Adjust the statement shapes if needed
(for example, state them with `Agree` from `HuffmanTable.lean`), but keep the
names, and record the final statements in your result.

- [ ] Definitions, the two lemmas, and an `Agree`-form corollary for use with `decodeSym_local`. Then `make test-lean` and commit.

### Task 3: Stored round trip (Lean)

**Files:** `spec/Deflate/Properties.lean`; `docs/verification-boundary.md` (remove the P11 stored-gap entry and list the new theorem).

**Produces:** `theorem decode_encodeStored (x : ByteArray) (limit : Nat) (h : x.size ≤ limit) : decode (encodeStored x) limit = .ok x`.

- [ ] Prove it by induction on `encodeStored.go`'s chunks, generalizing over the bytes already output and the reader position. `encodeStored_empty` stays and may become a corollary.
- [ ] Register the theorem. `make test-lean`. Commit.

### Task 4: Fixed-Huffman emitter (Lean)

**Files:** Create `spec/Deflate/EncodeFixed.lean`; add a section to `Properties.lean`.

**Consumes:** Tasks 1 and 2; `decodeSym_local`, `tableEntry` and the pattern readers from `HuffmanTable.lean`; `readLength`, `readDistance` and `copyGo` from `LZ77.lean`.

**Produces:**
```lean
def fixedLitCode (s : Nat) : Nat × Nat            -- (code, len), from "Shared formats"
def lengthSym (len : Nat) : Nat × Nat × Nat        -- (symbol, extra value, extra bits)
def distSym (dist : Nat) : Nat × Nat × Nat
def emitToken (w : BitWriter) : Token → BitWriter
def emitFixed (ts : List Token) : ByteArray
theorem fixedLit_code_decodes : ∀ s < 288, -- decodeSym fixedLitLen on a stream starting with fixedLitCode s returns s after (fixedLitCode s).2 bits
theorem fixedDist_code_decodes : ∀ s < 30, ...
theorem lengthSym_reads : ∀ len, 3 ≤ len → len ≤ 258 → -- readLength on the symbol and extra bits returns len
theorem distSym_reads : ∀ dist, 1 ≤ dist → dist ≤ 32768 → -- readDistance returns dist
theorem decode_emitFixed (ts : List Token) (limit : Nat) (hv : Valid ts) (hl : (expand ts).size ≤ limit) :
  decode (emitFixed ts) limit = .ok ⟨expand ts⟩
```

- [ ] Prove the symbol lemmas: a finite `decide +kernel` check per symbol on a pattern reader, then `decodeSym_local`. Prove the length and distance lemmas by `decide +kernel` over the ranges, or by a table argument if the kernel is too slow (32768 cases).
- [ ] Prove `decode_emitFixed` by induction on `ts`, with the invariant: the reader sits at the bit offset of the next token and `out = expand prefix`. Include fuel sufficiency for `emitFixed` streams: every symbol takes at least 7 bits, so `8 * size + 1` is enough. Do not touch the general P8 gap.
- [ ] Register `decode_emitFixed` and the four lemmas. `make test-lean`. Commit.

### Task 5: Model compressor and the Lean driver

**Files:** Create `spec/Deflate/Compress.lean`; modify `Properties.lean`, `spec/Main.lean` (oracle commands) and `axioms.lean`.

**Produces:**
```lean
def compress (find : Finder) (x : ByteArray) : ByteArray   -- smaller of emitFixed and encodeStored; ties go to stored
theorem decode_compress (find : Finder) (x : ByteArray) (limit : Nat) (h : x.size ≤ limit) :
  decode (compress find x) limit = .ok x
```

- [ ] Prove `decode_compress` from Tasks 1, 3 and 4.
- [ ] In `spec/Main.lean`, add the `EMIT` and `DEFLATE` commands per "Shared formats". `DEFLATE` uses `compress (fun _ _ => none)`.
- [ ] Smoke-check by hand: `printf 'EMIT l:41 m:3:1\n' | lake exe <driver>` returns `OK …`, and the Rust decoder decodes it to `AAAA`. `make test-lean`. Commit.

## Rust track (Tasks 6–10). Sequential; runs in parallel with the Lean track.

### Task 6: Tokens and the bit writer (Rust)

**Files:** Create `crates/deflate-core/src/tokens.rs` and `src/bitwriter.rs`; modify `src/lib.rs`; tests in `tests/encode_tests.rs`.

**Produces:**
```rust
pub enum Token { Literal(u8), Match { len: u16, dist: u16 } }    // dist up to 32768, which fits u16
pub fn expand(tokens: &[Token]) -> Result<Vec<u8>, Error>        // tests and oracle; uses lz77::copy_back
pub struct BitWriter { /* Vec<u8> plus a bit buffer */ }
impl BitWriter { pub fn new() -> Self; pub fn write_bits(&mut self, v: u32, n: u32); pub fn write_code(&mut self, code: u32, len: u32); pub fn bit_len(&self) -> usize; pub fn finish(self) -> Vec<u8> }
```

- [ ] Write the tests first. `write_bits` then `BitReader::read_bits` round-trips every `n` in 0..=32 at every start offset 0..=7, with random values. `write_code` against the fixed-code table from "Shared formats", checked through `HuffmanTable::decode` on `fixed_litlen()`. `expand` on literal and overlapping matches.
- [ ] Implement, run the gates, commit.

### Task 7: Fixed-Huffman emitter (Rust)

**Files:** Create `crates/deflate-core/src/encode_fixed.rs`; tests in `tests/encode_tests.rs`.

**Consumes:** Task 6.

**Produces:** `pub fn emit_fixed<I: IntoIterator<Item = Token>>(tokens: I) -> Vec<u8>`; `pub fn length_sym(len: u16) -> (u16, u32, u32)`; `pub fn dist_sym(dist: u16) -> (u16, u32, u32)`. The layout is exactly "Shared formats".

- [ ] Write the tests first:
  - `length_sym` over every `len` in 3..=258 and `dist_sym` over every `dist` in 1..=32768, decoded back through `lz77::read_length` and `read_distance` on a written stream;
  - `inflate(emit_fixed(ts)) == expand(ts)` for empty `ts`, every literal byte, len 258 at dist 1, dist 32768 after a 32768-byte prefix, and `dist == out.len()` (Review Focus 3).
- [ ] Implement, run the gates, commit.

### Task 8: Matcher (Rust)

**Files:** Create `crates/deflate-core/src/matcher.rs`; tests in `tests/encode_tests.rs`.

**Produces:** `pub fn tokens(input: &[u8]) -> impl Iterator<Item = Token> + '_` (greedy hash chains, mirroring Lean `compressTokens`); `pub fn accept(input: &[u8], i: usize, len: usize, dist: usize) -> bool`, mirroring Lean `accept`.

The design is spec §3.2:

- 3-byte hash, 32 KiB window, head and chain tables allocated once (fixed size, independent of input);
- chain length capped at 128;
- every emitted match passes `accept`.

- [ ] Write the tests first:
  - `expand(tokens(x)) == x`, and every match satisfies `accept`, on empty input, 1–3 byte inputs, random 64 KiB, 1 MiB zeros, `abc` repeated, and text;
  - `accept` rejects each bound and a byte mismatch.
- [ ] Implement, run the gates, commit.

### Task 9: `deflate` (Rust)

**Files:** Create `crates/deflate-core/src/compress.rs`; modify `src/lib.rs` (export `deflate`); tests in `tests/encode_tests.rs`.

**Produces:** `pub fn deflate(input: &[u8]) -> Vec<u8>`, mirroring Lean `compress`: the fixed stream from `emit_fixed(matcher::tokens(input))`, unless it is not smaller than `deflate_stored`'s exact size (`input.len() + 5 * max(1, ceil(len / 65535))`), in which case `deflate_stored(input)`.

- [ ] Write the tests first:
  - `inflate(deflate(x)) == x` for all of Review Focus 1–5, including the 65535, 65536 and 131071-byte boundaries;
  - random input gives output no larger than `deflate_stored`'s;
  - text is smaller than stored;
  - 1 MiB of zeros runs in under 1 s (debug).
- [ ] Implement, run the gates, commit.

### Task 10: CLI and oracle commands

**Files:** `crates/vdeflate/src/main.rs`, `crates/vdeflate/tests/cli_tests.rs`, `fuzz/fuzz_targets/roundtrip.rs`, `fuzz/Cargo.toml`.

- [ ] `-c` uses `deflate`, and `-c --stored` uses `deflate_stored`. Update the usage text.
- [ ] Add `--oracle` `DEFLATE` and `EMIT` per "Shared formats". A malformed token gives `ERR badToken`.
- [ ] Fuzz target `roundtrip`: `inflate(&deflate(data)) == data`.
- [ ] CLI tests:
  - `-c` then `-d` round-trips;
  - `-c --stored` output equals the old behaviour;
  - `EMIT l:41 m:3:1` gives `OK` with a hex string that `-d` decodes to `AAAA`.
- [ ] Run the gates with `-p vdeflate` too, then `cargo +nightly fuzz build roundtrip`. Commit.

## Integration (Tasks 11–12). After both tracks.

### Task 11: Differential harness

**Files:** `oracles/differential.py` (and `oracles/corpus.py` if the payloads need it).

- [ ] Add an encode-compressed phase:
  - for each corpus payload, Rust `DEFLATE` output must decode to the payload under the Rust decoder, the Lean model, zlib and lean-zip;
  - generate token lists (the Rust matcher's tokens for the payload, via a Rust `--oracle` helper or by re-tokenizing in Python, plus random valid token lists), and Rust `EMIT` must equal Lean `EMIT` byte for byte.
- [ ] Self-test: a deliberately broken emitter must be reported, for example a Python-side wrapper that flips one bit of Rust's `EMIT` output.
- [ ] Run `make test-differential` and the full `make test`. Fix any finding in the owning task's files. Commit.

### Task 12: Measurement and documents

**Files:**
- `crates/deflate-core/examples/perf.rs` (add a compress mode);
- `scripts/perf_report.sh`, `scripts/render_perf_tables.py`, `docs/perf-report.md` (a compression table: ratio and MB/s against `miniz_oxide` levels 1 and 6);
- `scripts/reports/*.json`, `docs/size-report.md`;
- `docs/conformance.md`, `docs/verification-boundary.md`, `docs/architecture.md`, `README.md`;
- create `docs/adr/0006-checked-matcher.md`.

- [ ] Add the compression measurement, record with `--record`, and run `make size`. `check_perf_report.sh` and `check_size_report.sh` must pass.
- [ ] ADR 0006 covers why the matcher checks every candidate: the proof holds for any finder, and the cost is only the check that scoring a candidate already does.
- [ ] Update the documents:
  - `conformance.md`: the encoder rows and the theorem counts;
  - `verification-boundary.md`: the new theorems, and the encoder boundary (Rust ↔ Lean by mirroring and differential only);
  - `README.md`: remove the "stored blocks only" gap.
- [ ] Run a fuzz smoke: `cargo +nightly fuzz run roundtrip -- -max_total_time=60`. Commit.

## Self-review against the spec

| Spec section | Task |
| --- | --- |
| §3.1 | 1, 6 |
| §3.2 | 1, 8 |
| §3.3 | 2, 6 |
| §3.4 | 4, 7 |
| §3.5 | 3 |
| §3.6 | 5 |
| §3.7 | 9 |
| §3.8 | 5, 10 |
| §4 | 6–11 |
| §5 | 12 |
| §7 | 1–12 |

The names match between the tracks: `compressTokens`/`tokens`,
`accept`/`accept`, `emitFixed`/`emit_fixed`, `compress`/`deflate`. The
Lean–Rust contract is the "Shared formats" section, which both tracks read.
