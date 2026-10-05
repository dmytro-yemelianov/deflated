# M7b: dynamic Huffman encoder, design

**Date:** 2026-10-06 · **Milestone:** spec §17 M7, second half · **Builds on:**
`2026-10-05-m7a-compressed-encoder-design.md` and its lemmas (`decode_emitFixed`,
`decodeSym_local`, `BitWriter` read-back, `decode_encodeStored`).

## 1. Intent

Improve the compression ratio by adding dynamic-Huffman blocks, without
weakening the M7a guarantee. `decode_compress`, which says the model
compressor round-trips **every** input for **every** finder, must still hold,
for the new `compress`.

Decided with the user:

- **Checked lengths.** Code lengths may come from any algorithm. They are
  checked (`validLengths`) before use, and a block whose lengths fail the
  check is emitted as fixed. The proof covers every valid length assignment,
  so the length-limiting heuristic is not proved.
- **Fixed-size token blocks.** Each block picks the smaller of dynamic and
  fixed. Stored stays the whole-stream fallback.
- Work happens on branch `m7b`, stacked on PR #1.

## 2. Validity: what the decoder accepts (`spec/Deflate/Block.lean`)

`readDynamicCodes` rejects a header unless all of these hold:

- the lit/len code is complete;
- the distance code satisfies `isValidDistance` (complete, or at most one used
  symbol, per ADR 0004);
- the code-length (CL) code is complete;
- `nlen ≤ 286`, `ndist ≤ 30`, and every length ≤ 15 (≤ 7 for the CL code).

So the encoder must establish all of these, as follows.

- `validLengths lit dist`:
  - `lit` has 257–286 entries, `dist` has 1–30 entries;
  - every entry is ≤ 15;
  - `lit` is Kraft-complete, and `dist` satisfies `isValidDistance`;
  - every symbol the block uses (each literal, 256, each length and distance
    symbol) has a nonzero length.
- **CL code.** It is built from the frequencies of the RLE symbols, limited to
  7, and must be complete. When only one CL symbol is used, a second one is
  given length 1 as well, so the code is complete. The same check-or-fallback
  rule applies.
- **No matches.** When a block has no matches, the distance code gets one
  symbol of length 1. This is accepted as degenerate.

## 3. Components

### 3.1 Canonical codes (Lean `spec/Deflate/Canonical.lean`, Rust `huffman.rs` encoder side)

- `canonicalCode (ls : Array Nat) (s : Nat) : Nat × Nat` gives `(code, len)`
  by the RFC 1951 §3.2.2 algorithm: bl_count, then next_code.
- **Key lemma** `decodeSym_canonical`: for `ls` complete, or valid as a
  distance code, with `ls[s] > 0`, `decodeSym ⟨ls⟩` on a stream whose next
  bits are `canonicalCode ls s` written MSB-first returns `s` after `ls[s]`
  bits.

  This generalizes M7a's `fixedLit_code_decodes`, which was proved by a
  finite `decide`. It needs a real proof over `decodeGo`'s
  `first`/`count`/`index` walk. The approach: show that the walk's `first` at
  length `l` equals next_code[l], and that symbols of length `l` sit at
  `index + (code - first)` in the canonical order. `decodeSym_local` lifts the
  result to any stream.

### 3.2 Header (Lean `spec/Deflate/EncodeDynamic.lean`)

- `rleLengths : Array Nat → List ClSym` uses symbols 0–15, 16 (repeat the
  previous 3–6 times), 17 (zeros, 3–10) and 18 (zeros, 11–138).
- `expandRle (rleLengths ls) = ls`, and every repeat count is in range.
- `emitHeader lit dist clLens` writes, in RFC 1951 §3.2.7 order:
  - HLIT, HDIST, HCLEN, with trailing zero CL lengths trimmed but at least 4;
  - the CL lengths in `clOrder`;
  - the RLE symbols with their extra bits, under the CL code.
- **Lemma** `readDynamicCodes_emitHeader`: under the validity in §2, the
  decoder reads back `(⟨lit⟩, ⟨dist⟩)` and stops at the header's end. Proved
  through `readCLLens`, `readCodeLengths` (whose RLE matches `rleLengths`) and
  `decodeSym_canonical` on the CL code.

### 3.3 Dynamic block and multi-block stream

- `emitDynamicBlock (final : Bool) (lit dist : Array Nat) (ts : List Token)`
  writes: the header bits `final`, then BTYPE = 10, then `emitHeader`, then
  each token under the canonical codes, then symbol 256.
- `emitBlock` uses dynamic when `validLengths` holds and its bit size is
  smaller than fixed's; otherwise it uses the M7a fixed block, non-final when
  needed. M7a's `emitFixed` gains a `final` parameter, or gets a non-final
  twin. This must keep `decode_emitFixed` as stated.
- Blocks share one `BitWriter`, so no byte alignment happens between blocks.
- `emitBlocks` splits the tokens into chunks of `blockTokens = 16384`.
  Every chunk except the last is non-final, and an empty token list gives one
  final block.

Lemmas:

- `decode_emitDynamicBlock`, for one block given the output so far;
- `decode_emitBlocks`: `Valid ts → (expand ts).size ≤ limit →
  decode (emitBlocks ts) limit = .ok ⟨expand ts⟩`.

  `Valid` is about the whole list, so a match may reach back into an earlier
  block, as RFC 1951 allows. Fuel: each block costs one unit of
  `decodeFuelLoop` and at least 10 bits, so the fuel suffices, as for stored.

### 3.4 Lengths (Rust only, unproved, checked)

`build_lengths(freqs, max_len) -> Vec<u8>`:

- Huffman by two queues over sorted frequencies;
- if the maximum length is above `max_len`, rebalance the overlong codes,
  miniz/zlib style;
- every symbol with nonzero frequency gets a nonzero length.

The result goes through the same `valid_lengths` as Lean's `validLengths`.
On failure, the block is fixed.

Lean has no heuristic. The model `compress` takes the lengths from a
parameter `lengthsFor : List Token → Option (Array Nat × Array Nat)`, which
works like `Finder`. The theorem holds for every `lengthsFor`. The oracle's
Lean `DEFLATE` uses `fun _ => none`, so it emits fixed blocks only, and
dynamic emission is compared through `EMITDYN` instead.

### 3.5 Model compressor

```lean
def compress (find : Finder) (lengthsFor : LengthsFor) (x : ByteArray) : ByteArray :=
  let b := emitBlocks lengthsFor (compressTokens find x.data)
  let s := encodeStored x
  if b.size < s.size then b else s
theorem decode_compress (find) (lengthsFor) (x) (limit) (h : x.size ≤ limit) :
  decode (compress find lengthsFor x) limit = .ok x
```

M7a's `compress` and `decode_compress` become the special case
`lengthsFor := fun _ => none`. Their emitted bytes stay equal to M7a's,
because a single fixed block for ≤ 16384 tokens has the same layout. Beyond
that the output becomes multiple fixed blocks; this is intended, and
`decode_compress` still holds.

### 3.6 Oracle

`EMITDYN <lit-lens hex> <dist-lens hex> <tok>*` emits one final block from
the given lengths, with dynamic chosen when they are valid and fixed
otherwise. Each length is one hex digit. It replies `OK <hex>`, and
`ERR badToken` / `ERR badLengths` for malformed input. Rust and Lean must be
byte-identical. `DEFLATE` is unchanged in form.

## 4. Testing

- **Rust unit:**
  - `canonical_code` against the decoder's table, for random valid lengths;
  - RLE round trip;
  - `build_lengths` gives valid lengths, the max-length limit holds, and
    every used symbol has a code (random frequency tables, including the
    edge cases of a single used symbol, all equal, and a geometric
    distribution);
  - `inflate(deflate(x)) == x` on the M7a Review Focus inputs plus inputs
    that cross block boundaries (16384 tokens ±1).
- **Differential:**
  - `EMITDYN` byte identity on random valid length sets, on the lengths the
    Rust heuristic produces for corpus payloads (exported through a Rust
    oracle helper `LENGTHS <tokens>`), and on invalid lengths, which must fall
    back identically;
  - `DEFLATE` checked by Rust, Lean and zlib;
  - self-test with a corrupted header bit.
- **Fuzz:** the `roundtrip` target covers the new path. Add a
  `dynamic_lengths` target: arbitrary frequencies to `build_lengths`, then
  `valid_lengths` must hold.

## 5. Measurement

Extend the compression table in `docs/perf-report.md` with the recorded
before/after numbers and miniz_oxide levels 1 and 6, and run `make size`.
There is no target before measuring.

## 6. Out of scope

Lazy matching, optimal parsing, adaptive block splitting, and proving the
length heuristic.

## 7. Done when

1. Lean proves `decodeSym_canonical`, `readDynamicCodes_emitHeader`,
   `decode_emitBlocks` and the generalized `decode_compress`. The gate is
   clean, and `decode_emitFixed` and the existing theorems are unchanged.
2. Rust `deflate` emits dynamic blocks where they are smaller. The
   differential (`EMITDYN`, `DEFLATE`) has 0 findings and its self-test
   passes.
3. The text ratio is measured and recorded. All gates pass, and the docs are
   updated: conformance, verification-boundary, perf-report and ADR 0006
   addendum or ADR 0007.
