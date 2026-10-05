# M7a: compressed encoder (LZ77 + fixed Huffman), design

**Date:** 2026-10-05 · **Milestone:** spec §17 M7, first half · **Follows:**
`docs/superpowers/plans/2026-10-05-verified-deflate.md` (M0–M6, M8) and the
perf work in `docs/perf-report.md`.

## 1. Intent

The encoder in v1 writes stored blocks only, so its output is larger than its
input. M7a makes `vdeflate -c` compress. It keeps to the project's order of
correctness first, then ratio (spec §4: maximum ratio is a non-goal).

The goal is the **proof**. Success means a Lean theorem that the model
compressor round-trips **every** input:

```lean
theorem decode_compress (find : Finder) (x : ByteArray) (limit : Nat)
    (h : x.size ≤ limit) : decode (compress find x) limit = .ok x
```

This holds for any match finder, which closes P10/P11 for the compressed
encoder. The Rust encoder is tied to that model the way the decoder is: by
mirroring its structure and by differential testing (ADR 0003).

Decided with the user during brainstorming:

- Proof first. Ratio is expected to be modest, around zlib levels 1–3.
- M7 is split. M7a, this spec, covers LZ77 and fixed Huffman. M7b (dynamic
  Huffman) gets its own spec and plan and builds on M7a's lemmas.
- Approach A: the matcher checks every candidate before emitting it, so the
  proof holds for any candidate finder.
- M7a also closes the recorded P11 gap for stored blocks (round trip for
  arbitrary input), because choosing between fixed and stored needs it.

## 2. Architecture

```text
input ──► matcher(find) ──► tokens ──► emitFixed ──┐
                                                   ├─► smaller of the two ──► stream
input ─────────────────────────────► encodeStored ─┘
```

Theorem structure, each part proved separately:

1. `expand (compressTokens find x) = x` and `valid (compressTokens find x)`,
   for any `find`. This is the matcher.
2. `valid ts → decode (emitFixed ts) limit = .ok (expand ts)` when
   `(expand ts).size ≤ limit`. This is the emitter.
3. `decode (encodeStored x) limit = .ok x` when `x.size ≤ limit`. This is the
   stored round trip for arbitrary input, closing the P11 gap.
4. `decode_compress` follows from 1–3 and the size comparison.

## 3. Components

### 3.1 Tokens (`spec/Deflate/Tokens.lean`, `crates/deflate-core/src/tokens.rs`)

```lean
inductive Token | literal (b : UInt8) | match (len dist : Nat)
def expand : List Token → Array UInt8   -- literal: push; match: copyGo
def Token.valid (outSize : Nat) : Token → Prop
  -- match: 3 ≤ len ≤ 258 ∧ 1 ≤ dist ≤ 32768 ∧ dist ≤ outSize
def valid : List Token → Prop           -- each token valid against expand of its prefix
```

`expand` uses the decoder's own `copyGo` (`LZ77.lean`), so the emitter theorem
can reuse the decoder's copy semantics instead of a second definition. Rust
`Token` is an enum with the same two cases; `expand` exists in Rust for tests
only.

### 3.2 Matcher (`spec/Deflate/Match.lean`, `crates/deflate-core/src/matcher.rs`)

```lean
abbrev Finder := Array UInt8 → Nat → Option (Nat × Nat)   -- (len, dist) candidate at i
def compressTokens (find : Finder) (x : Array UInt8) : List Token
```

At position `i` the matcher asks `find x i` for a candidate and accepts it
only when all of these hold:

- `3 ≤ len ≤ 258`, `1 ≤ dist ≤ 32768`, `dist ≤ i` and `i + len ≤ x.size`;
- `x[i+k] = x[i+k-dist]` for every `k < len`.

On acceptance it emits `match len dist` and continues at `i + len`; otherwise
it emits `literal x[i]` and continues at `i + 1`. Termination is by
`x.size - i`.

Theorems: `compressTokens_valid` and `expand_compressTokens`, both for every
`find`. The Lean finder used in tests and the oracle can be trivial, since
no theorem depends on it.

Rust finder:

- greedy hash chains over a 3-byte hash with a 32 KiB window and a bounded
  chain length;
- fixed memory, independent of input size: a head table and a window-sized
  chain array, about 192 KiB;
- the acceptance check mirrors Lean's. It happens while the candidate is
  scored, so a verified match costs no extra pass.

### 3.3 Bit writer (`spec/Deflate/BitWriter.lean`, `crates/deflate-core/src/bitwriter.rs`)

- State: the bytes written and the bit count in the open last byte.
- `writeBits v n` is LSB-first, matching `readBits`.
- `writeCode code len` writes a Huffman code MSB-first, i.e. `writeBits` of
  the bit-reversed code.
- `finish` pads the last byte with zeros.

The key lemma: reading back what was written, at the position it was written,
returns the value, whatever is written afterwards. It is stated with
`Agree` / `bitAt` from ADR 0005 so `decodeSym_local` applies directly.

### 3.4 Fixed-Huffman emitter (`spec/Deflate/EncodeFixed.lean`, `crates/deflate-core/src/encode_fixed.rs`)

```lean
def emitFixed (ts : List Token) : ByteArray
  -- header BFINAL=1 BTYPE=01, one symbol per token, then symbol 256, then pad
```

- `literal b` is written as the fixed code of `b`.
- `match len dist` is written as the length symbol and its extra bits, then
  the distance symbol and its extra bits. The tables are `LZ77.lean`'s.

Lemmas:

- **Symbol codes.** `decodeSym fixedLitLen` on the bits of `s`'s fixed code
  returns `s` after exactly `len s` bits, for all 288 symbols. Each case is a
  finite check on a pattern reader by `decide +kernel` (no `native_decide`);
  `decodeSym_local` lifts it to any stream. The same holds for `fixedDist`'s
  30 symbols.
- **Length and distance codes.** For every `len ∈ [3, 258]` and every
  `dist ∈ [1, 32768]`, the chosen symbol and extra bits make
  `readLength`/`readDistance` return the original value.
- **Fuel.** `decode` gives `decodeHuffBlock` `8 * bs.size + 1` fuel, and every
  symbol of `emitFixed`'s output takes at least 7 bits, so the fuel suffices
  for these streams. This is proved for `emitFixed` streams specifically. The
  general P8 gap stays open and recorded.
- **Headline.** `decode_emitFixed`: `valid ts → (expand ts).size ≤ limit →
  decode (emitFixed ts) limit = .ok (expand ts)`.

### 3.5 Stored round trip (`spec/Deflate/Properties.lean`)

`decode_encodeStored`: `x.size ≤ limit → decode (encodeStored x) limit = .ok x`,
for all `x`, by induction over the 65535-byte chunks. This replaces the P11
gap entry in `docs/verification-boundary.md`. The existing `encodeStored_empty`
stays as a corollary.

### 3.6 Model compressor

```lean
def compress (find : Finder) (x : ByteArray) : ByteArray :=
  let f := emitFixed (compressTokens find x.data)
  let s := encodeStored x
  if f.size < s.size then f else s
```

Ties go to stored, which decodes faster.

### 3.7 Rust encoder

- `pub fn deflate(input: &[u8]) -> Vec<u8>` mirrors `compress`.
  `deflate_stored` is unchanged.
- Tokens stream from the matcher straight into the emitter, with no
  `Vec<Token>`. If the finished fixed stream is not smaller than
  `encodeStored`'s size, which is computed exactly in advance, the result is
  replaced by `deflate_stored(input)`.
- Rules as for the rest of the core: `no_std`, `forbid(unsafe_code)`, no new
  dependencies, no panicking paths.

### 3.8 CLI and oracle protocol

- `vdeflate -c` uses `deflate`. `vdeflate -c --stored` keeps the old
  behaviour.
- `--oracle` keeps `ENCODE`, which stays stored, so the M6 harness is
  unchanged. It adds two commands:
  - `DEFLATE <hex>` → `deflate`;
  - `EMIT <token list>` → the emitter alone, for byte-exact comparison with
    Lean `emitFixed`.

  The Lean driver `spec/Main.lean` implements `EMIT` and `DEFLATE` with its
  trivial finder.

## 4. Testing

**Unit (Rust):**

- bit writer against bit reader, for every `n` in 0..=32 at every offset;
- symbol, length and distance mapping, exhaustively over `len` 3..=258 and
  `dist` 1..=32768;
- `expand(tokens) == input` and validity, on the corpus and on random,
  repetitive and empty inputs;
- every acceptance rule exercised by a finder that proposes bad candidates.

**Differential (`oracles/differential.py`, extended):**

- Rust `deflate` output is decoded by Rust, the Lean model, zlib and lean-zip,
  and all four must return the input;
- on the same token lists, Rust `EMIT` output must be byte-identical to Lean
  `emitFixed`;
- the wrong-oracle self-test gains a deliberately broken emitter that must be
  caught.

**Fuzz:** new `roundtrip` target, `inflate(deflate(x)) == x`.

**Lean gate:** unchanged rules. No `sorry`/`admit`/`native_decide`, standard
axioms only, and new headline theorems registered in `spec/scripts/axioms.lean`.

## 5. Measurement

Following `docs/perf-report.md`'s pattern, raw data in JSON and prose checked
against it:

- compression throughput and ratio against `miniz_oxide` levels 1 and 6 on
  the perf corpus;
- `make size` before and after, because the encoder adds code to `vdeflate`.

There is no ratio target before measuring (spec §17 M8's rule, applied
here).

## 6. Out of scope

- dynamic Huffman (M7b);
- lazy matching, multiple blocks, compression levels;
- streaming input;
- a refinement proof from Rust to Lean (ADR 0003 still applies).

## 7. Done when

1. `decode_compress`, `decode_emitFixed`, `expand_compressTokens`,
   `compressTokens_valid` and `decode_encodeStored` are proved and registered,
   with the Lean gate passing.
2. `docs/verification-boundary.md` no longer lists the stored P11 gap, and
   lists the compressed encoder's boundary: Rust ↔ Lean by mirroring and
   differential only.
3. The differential harness covers `DEFLATE` and `EMIT` with 0 findings, and
   the self-test catches the broken emitter.
4. `vdeflate -c` output on the perf corpus's `text` input is smaller than the
   stored encoding. The ratio is recorded, not targeted.
5. All gates pass: fmt, clippy, tests, differential, fuzz smoke, size and perf
   checks. `docs/conformance.md` and an ADR for the matcher-checks-candidates
   decision are updated or added.
