/-
  Deflate.EncodeFixed — the fixed-Huffman emitter (spec §3.4).

  One final block, BTYPE = 01 (RFC 1951 §3.2.6): the header bits, one symbol
  per token (a match also carries its length extra bits, distance code and
  distance extra bits), symbol 256, then zero padding to a byte. The length
  and distance tables are `Deflate.LZ77`'s, so the emitter and the decoder
  share one source of truth. `Properties.decode_emitFixed` is the round trip.
  Rust counterpart: `encode_fixed.rs`, which writes the same bytes.
-/
import Deflate.BitWriter
import Deflate.Tokens

namespace Deflate

/-- Fixed literal/length code of symbol `s` as `(code, length)`, RFC 1951
    §3.2.6: 0–143 are 8 bits from `0x30`, 144–255 are 9 bits from `0x190`,
    256–279 are 7 bits from 0, 280–287 are 8 bits from `0xC0`. -/
def fixedLitCode (s : Nat) : Nat × Nat :=
  if s < 144 then (0x30 + s, 8)
  else if s < 256 then (0x190 + (s - 144), 9)
  else if s < 280 then (s - 256, 7)
  else (0xC0 + (s - 280), 8)

/-- Largest `i < k` with `base[i] ≤ v`, or 0 if there is none. -/
def slotGo (base : Array Nat) (v : Nat) : Nat → Nat
  | 0 => 0
  | i + 1 => if base[i]! ≤ v then i else slotGo base v i

/-- Largest `i` with `base[i] ≤ v`; 0 if none (out-of-contract input).
    Rust: `slot`. -/
def slot (base : Array Nat) (v : Nat) : Nat := slotGo base v base.size

/-- `(symbol, extra value, extra bit count)` for a match length 3..258.
    Rust: `length_sym`. -/
def lengthSym (len : Nat) : Nat × Nat × Nat :=
  let i := slot lengthBase len
  (257 + i, len - lengthBase[i]!, lengthExtra[i]!)

/-- `(symbol, extra value, extra bit count)` for a distance 1..32768.
    Rust: `dist_sym`. -/
def distSym (dist : Nat) : Nat × Nat × Nat :=
  let i := slot distBase dist
  (i, dist - distBase[i]!, distExtra[i]!)

/-- Write one fixed literal/length symbol. Rust: `put_litlen`. -/
def writeLit (w : BitWriter) (s : Nat) : BitWriter :=
  w.writeCode (fixedLitCode s).1 (fixedLitCode s).2

/-- Emit one token: a literal's code, or a match's length symbol, length
    extra bits, 5-bit distance code and distance extra bits. -/
def emitToken (w : BitWriter) : Token → BitWriter
  | .literal b => writeLit w b.toNat
  | .match len dist =>
    let l := lengthSym len   -- (symbol, extra value, extra bits)
    let d := distSym dist
    (((writeLit w l.1).writeBits l.2.1 l.2.2).writeCode d.1 5).writeBits d.2.1 d.2.2

/-- The block header: BFINAL = 1, then BTYPE = 01 as two LSB-first bits. -/
def fixedHeader : BitWriter := (BitWriter.empty.writeBits 1 1).writeBits 1 2

/-- One final fixed-Huffman block holding `ts`. Rust: `emit_fixed`. -/
def emitFixed (ts : List Token) : ByteArray :=
  (writeLit (ts.foldl emitToken fixedHeader) 256).toBytes

end Deflate
