/-
  Deflate.Block — block headers (RFC 1951 §3.2.3) and stored blocks (§3.2.4).

  Header: BFINAL (1 bit), then BTYPE (2 bits):
    00 stored · 01 fixed Huffman · 10 dynamic Huffman · 11 reserved (error)

  Stored block: skip to the byte boundary, then LEN and NLEN as two
  little-endian 16-bit values, then LEN raw bytes. NLEN must be the ones'
  complement of LEN, which for 16 bits is `0xFFFF - LEN`.
-/
import Deflate.Bitstream

namespace Deflate

inductive BlockType where
  | stored | fixed | dynamic
  deriving Repr, DecidableEq, Inhabited

structure Header where
  isFinal : Bool
  btype   : BlockType
  deriving Repr, DecidableEq, Inhabited

def readHeader (r : BitReader) : Except DecErr (Header × BitReader) :=
  match BitReader.readBit r with
  | none => .error .unexpectedEof
  | some (f, r₁) =>
    match BitReader.readBits r₁ 2 with
    | none => .error .unexpectedEof
    | some (t, r₂) =>
      if t = 0 then .ok (⟨f, .stored⟩, r₂)
      else if t = 1 then .ok (⟨f, .fixed⟩, r₂)
      else if t = 2 then .ok (⟨f, .dynamic⟩, r₂)
      else .error .invalidBlockType

def readStored (r : BitReader) (out : Array UInt8) :
    Except DecErr (Array UInt8 × BitReader) :=
  let r₀ := BitReader.alignToByte r
  match BitReader.readBits r₀ 16 with
  | none => .error .unexpectedEof
  | some (len, r₁) =>
    match BitReader.readBits r₁ 16 with
    | none => .error .unexpectedEof
    | some (nlen, r₂) =>
      if nlen ≠ 0xFFFF - len then .error .invalidStoredLength
      else if r₂.size < r₂.pos + 8 * len then .error .unexpectedEof
      else
        let payload := (List.range len).map (fun k => byteAt r₂.bytes (r₂.pos / 8 + k))
        .ok (out ++ payload.toArray, { r₂ with pos := r₂.pos + 8 * len })

end Deflate
