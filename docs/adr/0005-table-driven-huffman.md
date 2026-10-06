# ADR 0005: Table-driven Huffman decoding

**Status:** accepted, implemented (Lean and Rust) · **Date:** 2026-10-05

## Context

`docs/perf-report.md` (current baseline, after candidates 1 and 2) puts
Huffman symbol decoding at the centre of the remaining gap on text:

- `text.dyn.deflate`: 1.78× slower than miniz_oxide, and `huffman::decode`
  is 64.3% of inclusive samples.
- `text.fixed.deflate`: 1.56× slower.
- Match-heavy inputs are already at or ahead of miniz_oxide, and table
  building does not show up in any profile.

`huffman::decode` reads one bit, compares against one code length, and
repeats, up to 15 times per symbol. That is the shape of the Lean
`decodeSym` (`decodeGo`), and it was chosen to keep the correspondence
direct. Perf candidate 3 replaces most of those steps with one table lookup.
Spec §16 requires an ADR and either a Lean lemma that the lookup equals the
canonical decode or an explicit statement that differential testing alone
covers it. This ADR records the lemma.

## Decision

- Add a **primary decode table** of `2^K` entries with **K = 12**
  (`Deflate.tableBits`), one per possible value of the next 12 stream bits.
- The table is defined **by evaluation**: the entry for pattern `p` is what
  the canonical decoder `decodeSym` does on a stream whose next bits are
  `p`. A symbol `s` decoded after consuming `l ≤ 12` bits gives the entry
  `(s, l)`; anything else (a longer code, an invalid pattern, running off
  the 16-bit pattern stream) gives **fallback**.
- **Fast decode** (`Deflate.decodeSymFast`): when at least 12 bits remain,
  peek them without consuming, look up; on `(s, l)` return `s` and advance
  by `l`; on fallback, or when fewer than 12 bits remain, run the canonical
  decoder unchanged from the original position.
- **No second-level tables.** Codes of 13 to 15 bits always take the
  canonical walk.
- The Lean model's block decoder (`decodeHuffBlock`, `readCodeLengths`) keeps
  calling `decodeSym`. Nothing in the model's semantics or in any existing
  theorem changes. The new theorem says the fast path equals `decodeSym`, and
  the Rust uses the fast path. The Rust therefore has one more definition to
  correspond to (`decodeSymFast`), and that definition is proved equal to the
  one it already corresponds to.

Definitions live in `spec/Deflate/HuffmanTable.lean`; theorems in the
"P2 — Table-driven Huffman decoding" section of
`spec/Deflate/Properties.lean`.

## Why table by evaluation

The alternative is the usual construction: for each symbol of length `L ≤ 12`,
bit-reverse its canonical code and write it into every slot whose low `L`
bits match. Specifying the table that way would make the Lean proof a
statement about canonical-code arithmetic, bit reversal and the Kraft
inequality, with special cases for incomplete distance codes (ADR 0004).

Defining the entry as "what `decodeSym` does on these bits" moves all of that
out of the proof. The correspondence argument then needs one property of
`decodeSym`, **locality**: it reads its input one bit at a time and looks at
nothing else, so a run that succeeds after `l` bits succeeds the same way on
any stream whose next `l` bits are the same (`decodeSym_local`). If the
entry for `p` is `(s, l)`, the decode of the pattern stream succeeded after
`l ≤ 12` bits. The real stream's next 12 bits *are* `p` (`readBits_bit`), so its
next `l` bits agree, and the canonical decode of the real stream returns
`(s, pos + l)`. That is what the fast path returned. On fallback, and near
the end of the stream, the fast path *is* the canonical decode. Hence
`decodeSymFast c (buildTable c) r = decodeSym c r`, on every reader, errors
included.

That equality holds for every `Code`, whether complete, incomplete or
degenerate, and for every reader. It needs no validity hypothesis, because an
entry is only a hit when `decodeSym` itself produced it.

## Why K = 12

The table began at nine bits and was widened in Rust at commit `271b35c`.
Lean now uses the same twelve-bit width. `decodeSymFastAt_eq` proves
equivalence for every width at most sixteen bits; `decodeSymFast_eq` and
both fixed-table totality theorems use the current width. A Rust test reads
Lean's constant and fails on drift. Twelve bits cover more dynamic codes in one lookup; this
is a speed and memory tradeoff, not a universal optimum.

The fixed codes need only nine bits for literal/length symbols and five
for distances. The totality proofs check those smaller pattern spaces by
kernel evaluation and lift to twelve bits with decoder locality. This
avoids enumerating the larger table inside the kernel.

## Table size cost

- **Memory:** 4096 entries × 2 bytes (`u16`, encoding below) = 8 KiB per table.
  A block needs one for literal/length and one for distance, 16 KiB total, held
  in `HuffmanTable` beside the existing `counts` and `symbols`. Using a table
  for the code-length code too is optional and costs another 8 KiB while the
  header is read.
- **Build time:** at most 4096 slot writes per table with the replication
  construction, against a block of thousands of symbols. Table construction
  is a small share of decoder samples on the benchmark corpus; tiny blocks
  may make the cost more significant.
- **Binary size:** the build loop and lookup are a few dozen instructions. If
  the two fixed tables are precomputed as `static` data instead of being built
  at runtime, that adds 16 KiB of read-only data. Measure with `make size`
  either way and record the delta, as spec §16 requires.

## Lean theorem names

In `spec/Deflate/Properties.lean`, all registered in `spec/scripts/axioms.lean`
and resting only on `propext`, `Quot.sound` and `Classical.choice`:

- `decodeSymFast_eq`: the headline. `decodeSymFast c (buildTable c) r = decodeSym c r`.
- `decodeSym_local`: locality of the canonical decoder.
- `buildTable_size`: the table has `2 ^ tableBits` entries.
- `tableEntry_some`: a hit has `0 < l ≤ tableBits` and `s < c.lengths.size`.
- `readBits_some`: with `readBits_eof`, the peek succeeds exactly when
  `pos + 12 ≤ size`.
- `fixedLitLen_table_total`, `fixedDist_table_total`: the fixed tables have
  no fallback entries.

Supporting lemmas: `readBits_bit` (bit `i` of the peeked value is stream bit
`pos + i`), `patternReader_bit`, `bitAt_eq_testBit`, `decodeGo_local`,
`buildTable_getD`.

## What the Rust must mirror

**Peek.** `peek_bits(12)` returns the same value `read_bits(12)` would, which is
the next 12 stream bits LSB first (stream bit `pos + i` is bit `i` of the
value), and does not move `pos`. It is only called when
`pos + 12 <= bit_len()`. This is the Lean `readBits r tableBits` returning
`some (p, _)`, where the second component is discarded.

**Entry encoding.** `u16`, with `0` meaning fallback, and otherwise
`(sym << 4) | len`, where `1 <= len <= 12`. `tableEntry_some` guarantees
`len >= 1` for every hit, so `0` is unambiguous. Every symbol is below 288,
so `sym << 4 | len` fits in a `u16`.

**Table contents.** For every `p` in `0..4096`, `table[p]` must encode
`tableEntry c p`: run the canonical decode on a stream whose first two bytes
are `[p & 0xff, p >> 8]`, starting at bit 0. If it returns `Ok(sym)` having
consumed `len <= 12` bits, the entry is `(sym, len)`. If it returns any error,
or consumed more than 12 bits, the entry is fallback. The Rust may build the
table this literal way, or with the replication construction (for each symbol
`s` with `1 <= L = len(s) <= 12` and canonical code `v`, set every slot
`reverse_bits(v, L) | (k << L)` for `k` in `0..2^(12-L)` to `(s, L)`; leave the
rest `0`). If it uses replication, a test must check it against the literal
construction for the fixed codes, for many random complete length sets, and
for the empty and one-symbol distance codes of ADR 0004.

**Decode.**

```text
decode_fast(r):
  if r.pos + 12 <= r.bit_len():
    e = table[r.peek_bits(12)]
    if e != 0:
      r.pos += e & 0xf
      return Ok(e >> 4)
  return decode(r)   // the existing canonical walk, unchanged, from the original pos
```

**Near the end of the stream.** When fewer than 12 bits remain, use the
canonical walk. Do not zero-pad the peek and look up: a padded pattern can
hit using padding bits, which would be wrong, and the version that checks
`len <= remaining` is a different algorithm that `decodeSymFast_eq` does not
cover.

**Fallback.** Fallback is always the canonical walk from the original
position, never a direct `Err(InvalidCode)`. This is load-bearing for errors:
a pattern that is invalid in the 16-bit pattern stream can reach
`UnexpectedEof` first in a real stream that ends sooner, and only the walk
reports that the way the model does. The fixed tables have no fallback
entries, and for dynamic codes it covers codes longer than 12 bits and the
unused half of a one-symbol distance code.

**Where it is used.** For the literal/length and distance decodes in
`decode_huff_block`. For the code-length code it is optional, because
`decodeSymFast_eq` holds for every code.

## Consequences

- The Rust decode algorithm changes, and its correspondence to the model now
  goes through `decodeSymFast_eq`. The Rust is still not proved: the
  differential harness remains the bridge (ADR 0003). The proof means a
  correctly mirrored fast path cannot change any decode result, so a
  differential finding after this change is a mirroring bug, not a design
  flaw.
- `huffman.rs`'s module comment ("No decode table is built") must be updated
  to point here.
- `docs/perf-report.md` candidate 3 moves to Done once the Rust lands and the
  report is re-run.
