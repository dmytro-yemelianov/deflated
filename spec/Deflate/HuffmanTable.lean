/-
  Deflate.HuffmanTable — table-driven Huffman decoding (ADR 0005).

  A fast path in front of the canonical decoder `decodeSym`, not a
  replacement for it. The table is defined *by evaluation*: the entry for a
  `tableBits`-bit pattern is whatever `decodeSym` does on a stream that starts
  with that pattern. `Properties.decodeSymFast_eq` proves the fast path equals
  `decodeSym` on every reader, results and errors alike, so every theorem
  about `decodeSym` carries over unchanged. The model's block decoder keeps
  calling `decodeSym`; the Rust uses this fast path and refines it.
-/
import Deflate.Huffman

namespace Deflate

/-- Width of the primary table: 9 bits, so every code of the fixed
    literal/length code (7 to 9 bits long) resolves in one lookup. -/
def tableBits : Nat := 9

/-- A table entry: `some (s, l)` means "symbol `s`, consume `l` bits";
    `none` means "fall back to `decodeSym`". -/
abbrev TableEntry := Option (Nat × Nat)

/-- Two bytes whose first `16` stream bits (LSB first, RFC 1951 §3.1.1) are
    the low 16 bits of `p`. For `p < 2 ^ tableBits`, stream bit `i` is
    `p.testBit i`, so the next `tableBits` bits read back as `p`. -/
def patternBytes (p : Nat) : ByteArray :=
  ⟨#[UInt8.ofNat p, UInt8.ofNat (p / 256)]⟩

/-- A reader at the start of `patternBytes p`. -/
def patternReader (p : Nat) : BitReader := ⟨patternBytes p, 0⟩

/-- The entry for pattern `p`: run the canonical decoder on a stream whose
    next bits are `p`. A symbol decoded within `tableBits` bits is a hit;
    anything else (a longer code, an invalid code) is a fallback. -/
def tableEntry (c : Code) (p : Nat) : TableEntry :=
  match decodeSym c (patternReader p) with
  | .ok (s, r') => if r'.pos ≤ tableBits then some (s, r'.pos) else none
  | .error _ => none

/-- The primary table: `2 ^ tableBits` entries, indexed by the pattern. -/
def buildTable (c : Code) : Array TableEntry :=
  Array.ofFn (n := 2 ^ tableBits) fun p => tableEntry c p.val

/-- Decode one symbol through a table. Peek `tableBits` bits without
    consuming them; when fewer remain, `readBits` is `none` and the
    canonical decoder runs. A hit consumes the entry's length; a fallback
    runs `decodeSym` from the original reader. -/
def decodeSymFast (c : Code) (tbl : Array TableEntry) (r : BitReader) :
    Except DecErr (Nat × BitReader) :=
  match BitReader.readBits r tableBits with
  | none => decodeSym c r
  | some (p, _) =>
    match tbl.getD p none with
    | some (s, l) => .ok (s, { r with pos := r.pos + l })
    | none => decodeSym c r

end Deflate
