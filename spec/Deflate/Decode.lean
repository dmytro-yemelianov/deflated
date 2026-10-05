/-
  Deflate.Decode — the decoder state machine (RFC 1951 §3.2.3).

  Read blocks until BFINAL. The loop is fuel-bounded and reports exhaustion
  as its own outcome rather than guessing; `Properties.decode_never_exhausts`
  shows the fuel the entry point supplies is always enough.
-/
import Deflate.Block

namespace Deflate

/-- Decode one block body: stored, fixed, or dynamic. -/
def decodeBlockBody (bs : ByteArray) (limit : Nat) (btype : BlockType)
    (r₁ : BitReader) (out : Array UInt8) : Except DecErr (Array UInt8 × BitReader) :=
  match btype with
  | .stored  => readStored r₁ out
  | .fixed   => decodeHuffBlock fixedLitLen fixedDist r₁ out limit (8 * bs.size + 1)
  | .dynamic => do
      let ((lit, dst), r₂) ← readDynamicCodes r₁
      decodeHuffBlock lit dst r₂ out limit (8 * bs.size + 1)

/-- Loop over blocks until BFINAL, bounded by `fuel`. -/
def decodeFuelLoop (bs : ByteArray) (limit : Nat) (r : BitReader) (out : Array UInt8) :
    Nat → Except DecErr ByteArray
  | 0 => .error .fuelExhausted
  | fuel + 1 => do
    let (h, r₁) ← readHeader r
    let (out', r₂) ← decodeBlockBody bs limit h.btype r₁ out
    if out'.size > limit then .error .outputLimitExceeded
    else if h.isFinal then .ok ⟨out'⟩
    else decodeFuelLoop bs limit r₂ out' fuel

/-- One pass over the block stream, bounded by `fuel`. -/
def decodeFuel (bs : ByteArray) (limit : Nat) (fuel : Nat) : Except DecErr ByteArray :=
  decodeFuelLoop bs limit ⟨bs, 0⟩ #[] fuel

/-- The model's entry point. Fuel is `8 * bs.size + 1`: one unit per bit of
    input, plus one, which `Properties.decode_never_exhausts` shows is enough
    because every block consumes at least one bit. -/
def decode (bs : ByteArray) (limit : Nat) : Except DecErr ByteArray :=
  decodeFuel bs limit (8 * bs.size + 1)

end Deflate
