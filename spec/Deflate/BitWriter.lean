/-
  Deflate.BitWriter — LSB-first bit writing (RFC 1951 §3.1.1), the inverse
  of `Deflate.Bitstream` (spec §3.3).

  The writer is a plain array of stream bits; `toBytes` packs them into
  bytes, least significant bit first, and zero-pads the last byte. Keeping
  bits rather than bytes makes "what was written at position `p`" a direct
  array lookup, which is all the read-back lemmas in `Deflate.Properties`
  need. Rust counterpart: `bitwriter.rs`, which packs bytes eagerly but
  produces the same output (`finish` there is `toBytes` here).
-/
import Deflate.Bitstream

namespace Deflate

/-- Bits written so far, in stream order. -/
structure BitWriter where
  bits : Array Bool
  deriving Repr, Inhabited

namespace BitWriter

/-- The empty writer. -/
def empty : BitWriter := ⟨#[]⟩

/-- The number `Σ_{i<n} f i · 2^i`: bits `f 0, f 1, …` read least
    significant first, the same recursion as `readBits`. -/
def natOfBits (f : Nat → Bool) : Nat → Nat
  | 0 => 0
  | n + 1 => (if f 0 then 1 else 0) + 2 * natOfBits (fun j => f (j + 1)) n

/-- The low `n` bits of `v`, least significant first. -/
def lsbBits (v n : Nat) : Array Bool := Array.ofFn (n := n) fun i => v.testBit i

/-- Append the low `n` bits of `v`, least significant first (RFC 1951
    §3.1.1 data elements). Rust: `write_bits`. -/
def writeBits (w : BitWriter) (v n : Nat) : BitWriter := ⟨w.bits ++ lsbBits v n⟩

/-- The low `len` bits of `code` in reverse order. -/
def reverseBits (code len : Nat) : Nat :=
  natOfBits (fun i => code.testBit (len - 1 - i)) len

/-- Append a `len`-bit Huffman code most significant bit first: `writeBits`
    of the bit-reversed code (RFC 1951 §3.1.1). Rust: `write_code`. -/
def writeCode (w : BitWriter) (code len : Nat) : BitWriter :=
  w.writeBits (reverseBits code len) len

/-- Byte `k` of the packed stream: bits `8k … 8k+7`, missing bits as 0. -/
def byteOf (bits : Array Bool) (k : Nat) : UInt8 :=
  UInt8.ofNat (natOfBits (fun j => bits.getD (8 * k + j) false) 8)

/-- Pack the bits into bytes, LSB first, zero-padding the last byte.
    Rust: `finish`. -/
def toBytes (w : BitWriter) : ByteArray :=
  ⟨Array.ofFn (n := (w.bits.size + 7) / 8) fun k => byteOf w.bits k⟩

end BitWriter
end Deflate
