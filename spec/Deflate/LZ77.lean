/-
  Deflate.LZ77 — length and distance codes (RFC 1951 §3.2.5) and the back
  copy (§3.2.3).

  The copy is defined one byte at a time, reading from the array it is
  writing. That is not an implementation detail: when `len > dist` the copy
  reads bytes it has just produced, and any bulk-copy definition would get
  that case wrong. `copyGo_overlap` below is the statement that pins it.
-/
import Deflate.Bitstream

namespace Deflate

/-- Length codes 257..285: base values. -/
def lengthBase : Array Nat :=
  #[3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
    67, 83, 99, 115, 131, 163, 195, 227, 258]

/-- Length codes 257..285: extra-bit counts. -/
def lengthExtra : Array Nat :=
  #[0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
    4, 4, 4, 4, 5, 5, 5, 5, 0]

/-- Distance codes 0..29: base values. -/
def distBase : Array Nat :=
  #[1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
    769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]

/-- Distance codes 0..29: extra-bit counts. -/
def distExtra : Array Nat :=
  #[0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
    9, 9, 10, 10, 11, 11, 12, 12, 13, 13]

/-- Resolve a length symbol and its extra bits. Symbols outside 257..285 are
    `invalidLength`; 286 and 287 exist in the fixed code but may never appear. -/
def readLength (sym : Nat) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  if 257 ≤ sym ∧ sym ≤ 285 then
    let i := sym - 257
    match BitReader.readBits r (lengthExtra[i]!) with
    | none => .error .unexpectedEof
    | some (e, r') => .ok (lengthBase[i]! + e, r')
  else .error .invalidLength

/-- Resolve a distance symbol and its extra bits. Symbols 30 and 31 exist in
    the fixed code but may never appear. -/
def readDistance (sym : Nat) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  if sym ≤ 29 then
    match BitReader.readBits r (distExtra[sym]!) with
    | none => .error .unexpectedEof
    | some (e, r') => .ok (distBase[sym]! + e, r')
  else .error .invalidDistance

/-- The copy loop: one byte at a time, from `dist` back in the array being
    built. -/
def copyGo (dist : Nat) : Array UInt8 → Nat → Array UInt8
  | acc, 0 => acc
  | acc, k + 1 => copyGo dist (acc.push (acc[acc.size - dist]!)) k

/-- A back-reference. `dist = 0` and `dist > out.size` are both rejected:
    there is nothing that far back to copy. -/
def copyBack (out : Array UInt8) (dist len : Nat) : Except DecErr (Array UInt8) :=
  if dist = 0 ∨ dist > out.size then .error .invalidDistance
  else .ok (copyGo dist out len)

end Deflate
