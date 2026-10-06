/-
  Deflate.Basic — shared vocabulary for the model.

  The theorems in this library are statements about *this model*. Nothing is
  extracted from or to Rust. What connects the model to `deflate-core` is the
  differential harness in `oracles/`, which is test evidence, not proof. See
  `docs/verification-boundary.md`.
-/
namespace Deflate

/-- A bit offset from the start of the compressed stream. -/
abbrev BitPos := Nat

/-- Deterministic failure modes. Mirrors `deflate_core::Error` name for name. -/
inductive DecErr where
  | unexpectedEof
  | invalidBlockType
  | invalidStoredLength
  | invalidHuffmanTree
  | invalidCode
  | invalidDistance
  | invalidLength
  | outputLimitExceeded
  /-- The decoder ran out of fuel. `decode_never_exhausts` in `Deflate.Fuel` shows
      this is unreachable at the fuel the entry point supplies. Reported
      explicitly rather than folded into another error: maked's cycle
      detector once answered "acyclic" on fuel exhaustion, which was wrong. -/
  | fuelExhausted
  deriving Repr, DecidableEq, Inhabited

/-- Total byte access: out of range reads as 0. Keeps every definition total
    so proofs never carry bounds side-conditions through arithmetic. -/
def byteAt (bs : ByteArray) (i : Nat) : UInt8 :=
  if h : i < bs.size then bs[i] else 0

theorem byteAt_oob (bs : ByteArray) (i : Nat) (h : ¬ i < bs.size) :
    byteAt bs i = 0 := by
  simp [byteAt, h]

end Deflate
