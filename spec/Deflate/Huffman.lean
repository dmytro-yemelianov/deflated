/-
  Deflate.Huffman — canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).

  Huffman codes are the one data element packed *most* significant bit first;
  everything else in the format is LSB first. Decoding therefore shifts one
  bit in at a time from the left.

  Representation: just the code lengths. RFC 1951 §3.2.2 fixes everything else
  — among codes of equal length, numeric values are assigned in increasing
  symbol order, and each length's codes occupy one contiguous numeric range.
  That is the counts/offsets decoder below, the same shape as zlib's puff.c.
-/
import Deflate.Bitstream

namespace Deflate

/-- RFC 1951 §3.2.7: no code is longer than 15 bits. -/
def maxCodeLen : Nat := 15

structure Code where
  /-- `lengths[s]` is symbol `s`'s code length; 0 means the symbol is unused. -/
  lengths : Array Nat
  deriving Repr, Inhabited

namespace Code

def countOf (c : Code) (len : Nat) : Nat :=
  c.lengths.toList.foldl (fun acc l => if l = len then acc + 1 else acc) 0

/-- Symbols of a given length in increasing symbol order — the canonical
    assignment order. -/
def symbolsOf (c : Code) (len : Nat) : List Nat :=
  (List.range c.lengths.size).filter (fun s => c.lengths[s]! = len)

/-- The Kraft sum, scaled by `2 ^ maxCodeLen` so it stays in `Nat`.
    A complete code sums to exactly `2 ^ maxCodeLen`. -/
def kraft (c : Code) : Nat :=
  (List.range (maxCodeLen + 1)).foldl
    (fun acc len => if len = 0 then acc else acc + c.countOf len * 2 ^ (maxCodeLen - len)) 0

/-- How many symbols the code actually assigns. -/
def used (c : Code) : Nat := c.lengths.size - c.countOf 0

/-- Exactly complete: the Kraft sum is `2 ^ maxCodeLen`. Required of the
    literal/length tree and the code-length tree (ADR 0004). -/
def isComplete (c : Code) : Bool := c.kraft = 2 ^ maxCodeLen

/-- Complete, or incomplete with at most one used symbol. Only a distance
    tree is allowed this (ADR 0004): real encoders emit a one-symbol or empty
    distance code for a block with no back-references. -/
def isValidDistance (c : Code) : Bool :=
  c.isComplete || (c.kraft < 2 ^ maxCodeLen && c.used ≤ 1)

end Code

/-- One decoding step: shift a bit in, then test whether the accumulated code
    falls in this length's range. -/
def decodeGo (c : Code) : Nat → Nat → Nat → BitReader → Nat → Except DecErr (Nat × BitReader)
  | _, _, _, _, 0 => .error .invalidCode
  | len, code, first, r, fuel + 1 =>
    match BitReader.readBit r with
    | none => .error .unexpectedEof
    | some (b, r₁) =>
      let code := code * 2 + (if b then 1 else 0)
      let cnt := c.countOf len
      if first ≤ code ∧ code - first < cnt then
        match (c.symbolsOf len)[code - first]? with
        | some s => .ok (s, r₁)
        | none   => .error .invalidCode
      else
        decodeGo c (len + 1) code ((first + cnt) * 2) r₁ fuel

/-- Decode one symbol. At most `maxCodeLen` bits are consumed; a code that
    does not resolve within them is `invalidCode`. -/
def decodeSym (c : Code) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  decodeGo c 1 0 0 r maxCodeLen

/-- RFC 1951 §3.2.6 literal/length code: lengths 8, 9, 7, 8 by range. -/
def fixedLitLen : Code :=
  ⟨((List.range 288).map fun s =>
      if s < 144 then 8 else if s < 256 then 9 else if s < 280 then 7 else 8).toArray⟩

/-- RFC 1951 §3.2.6 distance code: 32 symbols, 5 bits each. -/
def fixedDist : Code := ⟨(List.replicate 32 5).toArray⟩

end Deflate
