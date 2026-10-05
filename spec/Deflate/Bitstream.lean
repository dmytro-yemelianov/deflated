/-
  Deflate.Bitstream — LSB-first bit reading (RFC 1951 §3.1.1).

  "Data elements other than Huffman codes are packed starting with the least
  significant bit of the data element." Huffman codes are the exception; they
  are read most-significant-bit first and live in `Deflate.Huffman`.

  `readBits` recurses on the bit count rather than folding, so each theorem in
  `Deflate.Properties` is a one-line induction.
-/
import Deflate.Basic

namespace Deflate

deriving instance Repr for ByteArray

/-- A position in a compressed stream: the bytes, and a bit offset into them. -/
structure BitReader where
  bytes : ByteArray
  pos   : BitPos
  deriving Repr

namespace BitReader

/-- Total bits available. -/
def size (r : BitReader) : Nat := r.bytes.size * 8

/-- Bit `i` of the stream: bit `i % 8` of byte `i / 8`, least significant first. -/
def bitAt (bs : ByteArray) (i : Nat) : Bool :=
  (((byteAt bs (i / 8)).toNat >>> (i % 8)) &&& 1) == 1

/-- One bit, or `none` past the end. Past-the-end is the only failure. -/
def readBit (r : BitReader) : Option (Bool × BitReader) :=
  if r.pos < r.size then
    some (bitAt r.bytes r.pos, { r with pos := r.pos + 1 })
  else
    none

/-- `n` bits, least significant first. All-or-nothing: a short read returns
    `none` and no partially advanced reader, because the caller only ever sees
    the returned reader. -/
def readBits : BitReader → Nat → Option (Nat × BitReader)
  | r, 0       => some (0, r)
  | r, (n + 1) => do
      let (b, r₁) ← readBit r
      let (rest, r₂) ← readBits r₁ n
      pure ((if b then 1 else 0) + 2 * rest, r₂)

/-- Skip to the next byte boundary (RFC 1951 §3.2.4, stored blocks). -/
def alignToByte (r : BitReader) : BitReader :=
  { r with pos := (r.pos + 7) / 8 * 8 }

/-- `readBits` in the decoder's error monad: a short read is `unexpectedEof`. -/
def readBitsE (r : BitReader) (n : Nat) : Except DecErr (Nat × BitReader) :=
  match readBits r n with
  | none => .error .unexpectedEof
  | some p => .ok p

end BitReader
end Deflate
