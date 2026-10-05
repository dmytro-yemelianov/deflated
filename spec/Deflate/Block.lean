/-
  Deflate.Block — block headers (RFC 1951 §3.2.3) and stored blocks (§3.2.4).

  Header: BFINAL (1 bit), then BTYPE (2 bits):
    00 stored · 01 fixed Huffman · 10 dynamic Huffman · 11 reserved (error)

  Stored block: skip to the byte boundary, then LEN and NLEN as two
  little-endian 16-bit values, then LEN raw bytes. NLEN must be the ones'
  complement of LEN, which for 16 bits is `0xFFFF - LEN`.
-/
import Deflate.Bitstream
import Deflate.Huffman
import Deflate.LZ77

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

/-- Decode one Huffman-coded block body with the given literal/length and
    distance codes. Covers both fixed (RFC 1951 §3.2.6) and dynamic (§3.2.7)
    blocks: they differ only in where the two codes come from.

    `fuel` bounds the loop. `Properties.decodeHuffBlock_fuel_sufficient` shows
    that the fuel the entry point supplies is never exhausted on a finite
    stream, because each iteration consumes at least one bit. Reporting
    exhaustion explicitly rather than guessing is deliberate: maked's cycle
    detector once answered "acyclic" when it ran out of fuel. -/
def decodeHuffBlock (lit dist : Code) (r : BitReader) (out : Array UInt8)
    (limit : Nat) : Nat → Except DecErr (Array UInt8 × BitReader)
  | 0 => .error .fuelExhausted
  | fuel + 1 => do
    let (sym, r₁) ← decodeSym lit r
    if sym < 256 then
      if out.size ≥ limit then .error .outputLimitExceeded
      else decodeHuffBlock lit dist r₁ (out.push (UInt8.ofNat sym)) limit fuel
    else if sym = 256 then
      .ok (out, r₁)
    else do
      let (l, r₂) ← readLength sym r₁
      let (dsym, r₃) ← decodeSym dist r₂
      let (d, r₄) ← readDistance dsym r₃
      if out.size + l > limit then .error .outputLimitExceeded
      else do
        let o₁ ← copyBack out d l
        decodeHuffBlock lit dist r₄ o₁ limit fuel

/-- RFC 1951 §3.2.7: the order in which code-length code lengths appear.
    Frequently-used lengths come first so trailing zeros can be omitted. -/
def clOrder : Array Nat :=
  #[16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]

/-- Read `ncode` three-bit lengths and scatter them through `clOrder` into a
    19-entry array; positions not covered stay 0. -/
def readCLLens (r : BitReader) (ncode : Nat) : Except DecErr (Array Nat × BitReader) :=
  let rec go (i : Nat) (acc : Array Nat) (r : BitReader) :
      Except DecErr (Array Nat × BitReader) :=
    if i ≥ ncode then .ok (acc, r)
    else
      match BitReader.readBitsE r 3 with
      | .error e => .error e
      | .ok (v, r') => go (i + 1) (acc.set! (clOrder[i]!) v) r'
    termination_by ncode - i
  go 0 (Array.replicate 19 0) r

/-- Decode `total` code lengths with the code-length tree. Symbol 16 repeats
    the previous length 3..6 times, 17 repeats zero 3..10 times, 18 repeats
    zero 11..138 times. A 16 with nothing before it, and any repeat that
    would overrun `total`, are both `invalidHuffmanTree`. -/
def readCodeLengths (clCode : Code) (total : Nat) (r : BitReader) :
    Except DecErr (Array Nat × BitReader) :=
  let rec go (acc : Array Nat) (r : BitReader) (fuel : Nat) :
      Except DecErr (Array Nat × BitReader) :=
    match fuel with
    | 0 => .error .fuelExhausted
    | fuel + 1 =>
      if acc.size ≥ total then .ok (acc, r)
      else do
        let (sym, r₁) ← decodeSym clCode r
        if sym < 16 then
          go (acc.push sym) r₁ fuel
        else if sym = 16 then
          match acc.back? with
          | none => .error .invalidHuffmanTree
          | some prev => do
              let (e, r₂) ← BitReader.readBitsE r₁ 2
              let n := 3 + e
              if acc.size + n > total then .error .invalidHuffmanTree
              else go (acc ++ Array.replicate n prev) r₂ fuel
        else if sym = 17 then do
          let (e, r₂) ← BitReader.readBitsE r₁ 3
          let n := 3 + e
          if acc.size + n > total then .error .invalidHuffmanTree
          else go (acc ++ Array.replicate n 0) r₂ fuel
        else if sym = 18 then do
          let (e, r₂) ← BitReader.readBitsE r₁ 7
          let n := 11 + e
          if acc.size + n > total then .error .invalidHuffmanTree
          else go (acc ++ Array.replicate n 0) r₂ fuel
        else .error .invalidHuffmanTree
  go #[] r (total + 1)

/-- The dynamic block header (RFC 1951 §3.2.7). -/
def readDynamicCodes (r : BitReader) : Except DecErr ((Code × Code) × BitReader) := do
  let (hlit, r₁)  ← BitReader.readBitsE r 5
  let (hdist, r₂) ← BitReader.readBitsE r₁ 5
  let (hclen, r₃) ← BitReader.readBitsE r₂ 4
  let nlen  := hlit + 257
  let ndist := hdist + 1
  let ncode := hclen + 4
  -- RFC 1951 §3.2.7 caps these; the 5-bit fields can express more.
  if nlen > 286 ∨ ndist > 30 then .error .invalidHuffmanTree
  else do
    let (clLens, r₄) ← readCLLens r₃ ncode
    let clCode : Code := ⟨clLens⟩
    if ¬ clCode.isComplete then .error .invalidHuffmanTree
    else do
      let (lens, r₅) ← readCodeLengths clCode (nlen + ndist) r₄
      let lit : Code := ⟨lens.extract 0 nlen⟩
      let dst : Code := ⟨lens.extract nlen (nlen + ndist)⟩
      if ¬ lit.isComplete then .error .invalidHuffmanTree
      else if ¬ dst.isValidDistance then .error .invalidHuffmanTree
      else .ok ((lit, dst), r₅)

end Deflate
