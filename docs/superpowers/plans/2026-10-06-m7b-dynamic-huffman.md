# M7b Dynamic Huffman Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.
>
> **Token-efficient format (user requirement).** This plan gives names, signatures, theorem statements and acceptance criteria, not code bodies. Return a terse result and put the full report in the report file. Run only your own task's checks. The differential, perf, size and fuzz gates run once, in Tasks 8 and 9.

**Goal:** Dynamic-Huffman blocks in `deflate`, chosen per block where they are smaller, with `decode_compress` still proved for every input.

**Architecture:** Code lengths come from any algorithm and are checked by `validLengths`; blocks that fail the check fall back to fixed. Lean proves the canonical code decodes, the header round-trips, and multi-block streams decode. Rust adds the length heuristic and mirrors the emitter, and differential testing ties the two (ADR 0003).

**Tech Stack:** Lean 4 v4.30.0, Rust 1.88 (edition 2024), Python 3 oracles.

**Spec:** `docs/superpowers/specs/2026-10-06-m7b-dynamic-huffman-design.md`. Read §2 and your component's §3 subsection.

## Global Constraints

Same as M7a:

- Lean: no `sorry`, `admit` or `native_decide`; standard axioms only; headline theorems registered in `spec/scripts/axioms.lean`; `make test-lean`.
- Rust core: `no_std`, `forbid(unsafe_code)`, zero dependencies, no panicking paths; gates are fmt, clippy `-D warnings` and `cargo test -p deflate-core` (add `-p vdeflate` when the CLI changes).
- Existing theorem statements (`decode_emitFixed`, `decode_encodeStored`, `expand_compressTokens`, …) keep their exact statements. `decode_compress` may gain the `lengthsFor` parameter (spec §3.5).
- Commit with `git commit -- <paths>`, retrying on `index.lock`. End each message with the session's Co-Authored-By / Claude-Session lines.
- Branch `m7b`. Do not run `--record` or `size_report.sh` before Task 9.

## Spec amendment (ruling)

The CL code's lengths come from a heuristic too, so byte identity between Rust and Lean needs them passed explicitly:

- `LengthsFor` returns `Option (Array Nat × Array Nat × Array Nat)`: lit, dist and CL lengths, with the CL lengths indexed by CL symbol 0..18 (not in `clOrder`);
- `EMITDYN` takes three length arguments;
- `EMITDYN` emits dynamic whenever the lengths are valid, with no size comparison, so the dynamic path is always exercised.

## Shared formats (the bit-exact contract for Tasks 2–4 and 5–7)

- **Lengths as hex.** One hex digit per length, concatenated, e.g. `88889`. `lit` has 257–286 digits, `dist` 1–30, `cl` exactly 19 (indexed by CL symbol).
- **Trimming.** `HLIT = lit.size - 257` and `HDIST = dist.size - 1`, using the arrays as given. The emitter does not trim; trimming (`max(257, last nonzero + 1)` and `max(1, last nonzero + 1)`) is the caller's job (`lengths_for` / `lengthsFor`). `HCLEN = max(4, (last i with cl[clOrder[i]] ≠ 0) + 1) - 4`.
- **RLE (`rleLengths`).** Runs are taken over `lit ++ dist` concatenated, so a run may cross the boundary. Scanning left to right, take a maximal run of value `v` with length `n`:
  - if `v = 0`:
    - while `n ≥ 11`, emit `18` with `min(n, 138) - 11` in 7 extra bits and subtract that count;
    - then, if `n ≥ 3`, emit `17` with `n - 3` in 3 bits and set `n = 0`;
    - then emit `0` `n` times;
  - if `v ≠ 0`:
    - emit `v` and set `n -= 1`;
    - while `n ≥ 3`, emit `16` with `min(n, 6) - 3` in 2 bits and subtract that count;
    - then emit `v` `n` times.
- **Validity (`validLengths lit dist cl ts`):**
  - sizes in range;
  - lit and dist lengths ≤ 15, CL lengths ≤ 7;
  - `lit` complete, `dist` satisfies `isValidDistance`, `cl` complete;
  - every symbol used by `ts` has a nonzero length: literals, 256, length symbols, distance symbols;
  - every CL symbol used by `rleLengths (lit ++ dist)` has a nonzero CL length.
- **Dynamic block bits:**
  - `final` (1 bit), then `writeBits 2 2` (BTYPE = 10);
  - HLIT (5), HDIST (5), HCLEN (4), then `HCLEN + 4` CL lengths in `clOrder`, 3 bits each;
  - the RLE symbols under the CL code (`writeCode`), each followed by its extra bits;
  - the tokens as in M7a, but under `canonicalCode lit` / `canonicalCode dist`;
  - finally `canonicalCode lit 256`.
- **Canonical code** (RFC 1951 §3.2.2):
  - `bl_count`;
  - `next_code[l] = (next_code[l-1] + bl_count[l-1]) << 1`, with `bl_count[0] = 0`;
  - symbols are assigned codes in increasing symbol order within each length.
- **Blocks.** Tokens are cut into chunks of 16384; the last chunk, or the only (possibly empty) chunk, is final. Blocks share one bit writer, and only the very end pads to a byte.
- **Per-block choice in `deflate`/`compress`.** Use dynamic iff the lengths are `Some` and valid and `dynBits < fixedBits`; otherwise fixed. The fixed block layout is M7a's, with the final bit as given.
- **Oracle.** `EMITDYN <lit> <dist> <cl> <tok>*` gives one final block: dynamic if valid, fixed otherwise. Replies are `OK <hex>`, `ERR badLengths` (bad hex or bad sizes) and `ERR badToken`. Rust-only `LENGTHS <tok>*` replies `OK <lit> <dist> <cl>`, or `OK none` when the heuristic declines; these are the lengths `deflate` would use.

---

## Lean track (Tasks 1–4, sequential)

### Task 1: Canonical codes

**Files:** create `spec/Deflate/Canonical.lean`; add a section to `Properties.lean`.

**Produces:**
- `def canonicalCode (ls : Array Nat) (s : Nat) : Nat × Nat`
- `theorem decodeSym_canonical`. Statement: for `ls` with every entry ≤ 15, and either `(⟨ls⟩ : Code).isComplete` or `isValidDistance`, and `s < ls.size` with `ls[s] > 0`: writing `canonicalCode ls s` with `writeCode` at any point of a stream and reading there with `decodeSym ⟨ls⟩` gives `s` after `ls[s]` bits. Use the stream-position form that M7a's `fixedLit_code_decodes` uses (`EncodeFixed.lean`).
- `theorem canonicalCode_fixed`, which ties the fixed tables to `canonicalCode`; useful, optional.

- [ ] Prove it via the invariant of `decodeGo`: at length `l`, `first` = next_code[l] and `index` = the number of symbols shorter than `l`. Then `decodeSym_local`. Register the theorem; run `make test-lean`; commit.

### Task 2: RLE and header

**Files:** create `spec/Deflate/EncodeDynamic.lean`; add to `Properties.lean`.

**Consumes:** Task 1, and `readDynamicCodes`, `readCLLens`, `readCodeLengths` and `clOrder` from `Block.lean`.

**Produces:**
- `inductive ClSym | len (v : Nat) | rep16 (n : Nat) | zeros17 (n : Nat) | zeros18 (n : Nat)`
- `def rleLengths : Array Nat → List ClSym`
- `def emitHeader (w : BitWriter) (lit dist cl : Array Nat) : BitWriter`
- `theorem rleLengths_expand`
- `theorem readDynamicCodes_emitHeader`: under the header part of `validLengths`, `readDynamicCodes` at the header start returns `.ok ((⟨lit⟩, ⟨dist⟩), r)` with `r.pos` at the header end, and this holds whatever follows.

- [ ] Prove, register, run `make test-lean`, commit.

### Task 3: Dynamic block and multi-block

**Files:** add to `EncodeDynamic.lean`, plus `EncodeFixed.lean` (a non-final variant that leaves `emitFixed` and `decode_emitFixed` untouched) and `Properties.lean`.

**Produces:**
- `def validLengths (lit dist cl : Array Nat) (ts : List Token) : Bool`
- `abbrev LengthsFor := List Token → Option (Array Nat × Array Nat × Array Nat)`
- `def emitDynamicBlock (w : BitWriter) (final : Bool) (lit dist cl : Array Nat) (ts : List Token) : BitWriter`
- `def emitBlock` (the per-block choice from "Shared formats")
- `def emitBlocks (lf : LengthsFor) (ts : List Token) : ByteArray`
- `theorem decode_emitBlocks (lf) (ts) (limit) (hv : Valid ts) (hl : (expand ts).size ≤ limit) : decode (emitBlocks lf ts) limit = .ok ⟨expand ts⟩`

- [ ] Prove with a per-block lemma, generalized over the output prefix and reader position, then induct over the chunks. Matches may reach back across blocks. Fuel: one unit per block, and each block is ≥ 10 bits. Register, run `make test-lean`, commit.

### Task 4: Generalized compressor and Lean driver

**Files:** `Compress.lean`, `Properties.lean`, `spec/Main.lean`, `axioms.lean`, and `docs/verification-boundary.md` and `docs/conformance.md` (theorem counts and the proved list).

**Produces:**
- `def compress (find : Finder) (lf : LengthsFor) (x : ByteArray) : ByteArray`
- `theorem decode_compress (find) (lf) (x) (limit) (h : x.size ≤ limit) : decode (compress find lf x) limit = .ok x`

- [ ] Update `compress` and `decode_compress` (spec §3.5). The driver's `DEFLATE` uses `compress (fun _ _ => none) (fun _ => none)`. Add `EMITDYN` per "Shared formats".
- [ ] Smoke check: an `EMITDYN` with hand-made valid lengths decodes with `vdeflate -d` once that exists, otherwise with Python `zlib.decompress(…, -15)`. Run `make test-lean`, then commit.

## Rust track (Tasks 5–7, sequential, in parallel with the Lean track)

### Task 5: Lengths, canonical codes and RLE

**Files:** create `crates/deflate-core/src/huffman_build.rs`; tests in `tests/encode_dynamic_tests.rs`.

**Produces:**
- `pub fn build_lengths(freqs: &[u32], max_len: u8) -> Vec<u8>` (spec §3.4)
- `pub fn canonical_codes(lengths: &[u8]) -> Vec<(u16, u8)>`
- `pub enum ClSym { Len(u8), Rep16(u8), Zeros17(u8), Zeros18(u8) }`
- `pub fn rle_lengths(lengths: &[u8]) -> Vec<ClSym>`
- `pub fn valid_lengths(lit: &[u8], dist: &[u8], cl: &[u8], used: &UsedSymbols) -> bool`
- `pub struct UsedSymbols`, a bitset of lit/len and dist symbols

All exactly as in "Shared formats".

- [ ] Tests first:
  - `canonical_codes` decode through `HuffmanTable::decode` for random valid lengths;
  - `rle_lengths` expands back, and the RLE golden vectors (runs of 1, 2, 3, 6, 7, 10, 11, 138, 139 and 140, with zeros and non-zeros) match the "Shared formats" algorithm;
  - `build_lengths` on random, single-symbol, all-equal and geometric (2^k) frequencies gives lengths ≤ `max_len`, with every nonzero frequency getting a nonzero length, and with Kraft-complete output whenever ≥ 2 symbols are used.
- [ ] Implement, run the gates, commit.

### Task 6: Dynamic emitter and `deflate`

**Files:** create `crates/deflate-core/src/encode_dynamic.rs`; modify `compress.rs` (`deflate`) and `encode_fixed.rs` (non-final variant).

**Produces:**
- `pub fn lengths_for(tokens: &[Token]) -> Option<(Vec<u8>, Vec<u8>, Vec<u8>)>`, which counts, builds (`max_len` 15, 7 for CL), applies the degenerate-distance and single-CL-symbol fixes from spec §2, and trims;
- `pub fn emit_dynamic_block(w: &mut BitWriter, final_: bool, lit: &[u8], dist: &[u8], cl: &[u8], tokens: &[Token])`;
- `pub fn emit_blocks(tokens: &[Token]) -> Vec<u8>`.

`deflate` = `emit_blocks(tokens)` against stored, per "Shared formats". The tokens are buffered per 16384-token chunk.

- [ ] Tests first:
  - `inflate(deflate(x)) == x` on all the M7a Review Focus inputs, plus 16383, 16384 and 16385 tokens, plus a block with no matches, plus a single repeated byte;
  - text compresses smaller than M7a did; record both sizes.
- [ ] Implement, run the gates, commit.

### Task 7: CLI oracle and fuzz

**Files:** `crates/vdeflate/src/main.rs`, `cli_tests.rs`, `fuzz/fuzz_targets/dynamic_lengths.rs`, `fuzz/Cargo.toml`.

- [ ] Add `EMITDYN` and `LENGTHS` per "Shared formats", with CLI tests for both and for their errors.
- [ ] Add a fuzz target: arbitrary `u32` frequencies, then `build_lengths`; check that the lengths are valid and that used symbols are nonzero.
- [ ] Gates, then `cargo +nightly fuzz build dynamic_lengths`; commit.

## Integration

### Task 8: Differential

**Files:** `oracles/differential.py`.

- [ ] Add an `EMITDYN` phase, checking Rust == Lean byte for byte on:
  - lengths from `LENGTHS` for corpus payloads (tokenized as in M7a);
  - random valid length sets (generated in Python by building canonical lengths);
  - invalid lengths, which both sides must fall back on identically.
- [ ] `DEFLATE`: Rust output decodes correctly under Rust, Lean and zlib.
- [ ] Self-test: Rust `EMITDYN` with a flipped header bit must be caught.
- [ ] Run `make test-differential` and `make test`, then commit.

### Task 9: Measurement and docs

- [ ] `--record` the perf report; the compression table gains the M7b rows. Run `make size`; both check scripts must pass.
- [ ] Add ADR 0007 (checked code lengths, fixed fallback, block size 16384).
- [ ] Update `conformance.md`, `verification-boundary.md` (the new theorems; the heuristic is unproved but checked) and `README.md`.
- [ ] Run the `roundtrip` and `dynamic_lengths` fuzz targets for 60 s each, then commit.

## Self-review

| Spec section | Task |
| --- | --- |
| §2 | 3, 5, 6 |
| §3.1 | 1, 5 |
| §3.2 | 2, 5, 6 |
| §3.3 | 3, 6 |
| §3.4 | 5, 6 |
| §3.5 | 4, 6 |
| §3.6 | 4, 7 |
| §4 | 5–8 |
| §5 | 9 |

The one amendment (CL lengths passed explicitly) is ruled above. Names pair one-to-one between Lean and Rust:

| Lean | Rust |
| --- | --- |
| `canonicalCode` | `canonical_codes` |
| `rleLengths` | `rle_lengths` |
| `validLengths` | `valid_lengths` |
| `emitDynamicBlock` | `emit_dynamic_block` |
| `emitBlocks` | `emit_blocks` |
