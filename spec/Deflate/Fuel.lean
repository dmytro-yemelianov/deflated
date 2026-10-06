/- Fuel bounds for every input, including malformed streams. -/
import Deflate.Properties

namespace Deflate

theorem readBitsE_never_exhausts (r : BitReader) (n : Nat) :
    r.readBitsE n ≠ .error .fuelExhausted := by
  unfold BitReader.readBitsE
  split <;> simp

theorem decodeGo_never_exhausts (c : Code) (fuel len code first : Nat) (r : BitReader) :
    decodeGo c len code first r fuel ≠ .error .fuelExhausted := by
  induction fuel generalizing len code first r with
  | zero => simp [decodeGo]
  | succ fuel ih =>
    unfold decodeGo
    repeat' first
      | exact ih _ _ _ _
      | solve | simp
      | (split <;> try dsimp only)

theorem decodeSym_never_exhausts (c : Code) (r : BitReader) :
    decodeSym c r ≠ .error .fuelExhausted :=
  decodeGo_never_exhausts c _ _ _ _ r

theorem readLength_never_exhausts (sym : Nat) (r : BitReader) :
    readLength sym r ≠ .error .fuelExhausted := by
  unfold readLength
  split
  · dsimp only; split <;> simp
  · simp

theorem readDistance_never_exhausts (sym : Nat) (r : BitReader) :
    readDistance sym r ≠ .error .fuelExhausted := by
  unfold readDistance
  split
  · split <;> simp
  · simp

theorem copyBack_never_exhausts (out : Array UInt8) (dist len : Nat) :
    copyBack out dist len ≠ .error .fuelExhausted := by
  unfold copyBack
  split <;> simp

theorem readCodeLengths_go_fuel_sufficient (c : Code) (total fuel : Nat)
    (acc : Array Nat) (r : BitReader) (hf : total - acc.size < fuel) :
    readCodeLengths.go c total acc r fuel ≠ .error .fuelExhausted := by
  induction fuel generalizing acc r with
  | zero => omega
  | succ fuel ih =>
    intro h
    rw [readCodeLengths.go] at h
    dsimp only [Bind.bind, Except.bind] at h
    repeat' first
      | contradiction
      | (exact decodeSym_never_exhausts _ _ ‹_›)
      | (exact readBitsE_never_exhausts _ _ ‹_›)
      | (exact ih _ _ (by simp only [Array.size_push, Array.size_append,
          Array.size_replicate]; omega) h)
      | (split at h <;> try dsimp only [Bind.bind, Except.bind] at h)
      | (cases h)

theorem readCodeLengths_never_exhausts (c : Code) (total : Nat) (r : BitReader) :
    readCodeLengths c total r ≠ .error .fuelExhausted := by
  exact readCodeLengths_go_fuel_sufficient c total (total + 1) #[] r (by simp)

theorem readCLLens_go_never_exhausts (ncode i : Nat) (acc : Array Nat) (r : BitReader) :
    readCLLens.go ncode i acc r ≠ .error .fuelExhausted := by
  intro h
  rw [readCLLens.go] at h
  split at h
  · contradiction
  · split at h
    · cases h; exact readBitsE_never_exhausts _ _ ‹_›
    · exact readCLLens_go_never_exhausts _ _ _ _ h
termination_by ncode - i

theorem readCLLens_never_exhausts (r : BitReader) (ncode : Nat) :
    readCLLens r ncode ≠ .error .fuelExhausted :=
  readCLLens_go_never_exhausts _ _ _ _

private theorem bind_never_exhausts {α β : Type} (x : Except DecErr α)
    (f : α → Except DecErr β) (hx : x ≠ .error .fuelExhausted)
    (hf : ∀ a, x = .ok a → f a ≠ .error .fuelExhausted) :
    x >>= f ≠ .error .fuelExhausted := by
  cases x with
  | error e => simpa [Bind.bind, Except.bind] using hx
  | ok a => exact hf a rfl

theorem readDynamicCodes_never_exhausts (r : BitReader) :
    readDynamicCodes r ≠ .error .fuelExhausted := by
  unfold readDynamicCodes
  apply bind_never_exhausts _ _ (readBitsE_never_exhausts _ _)
  rintro ⟨hlit, r₁⟩ _
  apply bind_never_exhausts _ _ (readBitsE_never_exhausts _ _)
  rintro ⟨hdist, r₂⟩ _
  apply bind_never_exhausts _ _ (readBitsE_never_exhausts _ _)
  rintro ⟨hclen, r₃⟩ _
  dsimp only
  split
  · simp
  · apply bind_never_exhausts _ _ (readCLLens_never_exhausts _ _)
    rintro ⟨clLens, r₄⟩ _
    dsimp only
    split
    · simp
    · apply bind_never_exhausts _ _ (readCodeLengths_never_exhausts _ _ _)
      rintro ⟨lens, r₅⟩ _
      dsimp only
      split
      · simp
      · split <;> simp

private theorem decodeSym_starts_lt {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) : r.pos < r.size := by
  unfold decodeSym at h
  simp only [maxCodeLen, decodeGo] at h
  split at h
  · contradiction
  · exact readBit_lt ‹_›

/-- One unit per remaining input bit, plus one for observing EOF, suffices. -/
theorem decodeHuffBlock_fuel_sufficient (fuel : Nat) (lit dist : Code)
    (r : BitReader) (out : Array UInt8) (limit : Nat)
    (hf : r.size - r.pos < fuel) :
    decodeHuffBlock lit dist r out limit fuel ≠ .error .fuelExhausted := by
  induction fuel generalizing r out with
  | zero => omega
  | succ fuel ih =>
    unfold decodeHuffBlock
    apply bind_never_exhausts _ _ (decodeSym_never_exhausts _ _)
    rintro ⟨sym, r₁⟩ hs
    have hp := (decodeSym_pos hs).1
    have hb := decodeSym_bytes hs
    have hlt := decodeSym_starts_lt hs
    dsimp only
    split
    · split
      · simp
      · apply ih
        simp only [BitReader.size, hb] at *
        dsimp [BitPos] at *
        omega
    · split
      · simp
      · apply bind_never_exhausts _ _ (readLength_never_exhausts _ _)
        rintro ⟨l, r₂⟩ hl
        apply bind_never_exhausts _ _ (decodeSym_never_exhausts _ _)
        rintro ⟨dsym, r₃⟩ hd
        apply bind_never_exhausts _ _ (readDistance_never_exhausts _ _)
        rintro ⟨d, r₄⟩ hr
        dsimp only
        split
        · simp
        · apply bind_never_exhausts _ _ (copyBack_never_exhausts _ _ _)
          intro o₁ _
          apply ih
          have hp₂ := readLength_pos hl
          have hp₃ := (decodeSym_pos hd).1
          have hp₄ := readDistance_pos hr
          have hb₂ := readLength_bytes hl
          have hb₃ := decodeSym_bytes hd
          have hb₄ := readDistance_bytes hr
          simp only [BitReader.size, hb₄, hb₃, hb₂, hb] at *
          dsimp [BitPos] at *
          omega

theorem readHeader_never_exhausts (r : BitReader) :
    readHeader r ≠ .error .fuelExhausted := by
  unfold readHeader
  repeat' first | (solve | simp) | split

theorem readStored_never_exhausts (r : BitReader) (out : Array UInt8) :
    readStored r out ≠ .error .fuelExhausted := by
  unfold readStored
  dsimp only
  repeat' first | (solve | simp) | split

private theorem readHeader_starts_lt {r r' : BitReader} {h : Header}
    (hh : readHeader r = .ok (h, r')) : r.pos < r.size := by
  unfold readHeader at hh
  split at hh
  · contradiction
  · exact readBit_lt ‹_›

theorem decodeBlockBody_never_exhausts (bs : ByteArray) (limit : Nat)
    (btype : BlockType) (r : BitReader) (out : Array UInt8) (hb : r.bytes = bs) :
    decodeBlockBody bs limit btype r out ≠ .error .fuelExhausted := by
  cases btype with
  | stored => exact readStored_never_exhausts _ _
  | fixed =>
    apply decodeHuffBlock_fuel_sufficient
    simp only [BitReader.size, hb]
    omega
  | dynamic =>
    unfold decodeBlockBody
    apply bind_never_exhausts _ _ (readDynamicCodes_never_exhausts _)
    rintro ⟨⟨lit, dst⟩, r₂⟩ hd
    apply decodeHuffBlock_fuel_sufficient
    have hb₂ := (readDynamicCodes_pos hd).2
    simp only [BitReader.size, hb₂, hb]
    omega

/-- Every successful block body preserves input bytes and advances or stays put. -/
theorem decodeBlockBody_pos {bs : ByteArray} {limit : Nat} {btype : BlockType}
    {r r' : BitReader} {out o : Array UInt8}
    (h : decodeBlockBody bs limit btype r out = .ok (o, r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  cases btype with
  | stored =>
    have hb := readStored_bytes h
    have hp := (readStored_consumes h).2
    refine ⟨?_, hb⟩
    dsimp [BitReader.alignToByte, BitPos] at *
    omega
  | fixed =>
    have hp := decodeHuffBlock_monotone _ _ _ _ _ _ _ _ h
    exact ⟨hp.2.2, hp.2.1⟩
  | dynamic =>
    unfold decodeBlockBody at h
    cases hd : readDynamicCodes r with
    | error e => simp [hd, Bind.bind, Except.bind] at h
    | ok p =>
      rcases p with ⟨⟨lit, dst⟩, r₂⟩
      simp only [hd, Bind.bind, Except.bind] at h
      have hp := decodeHuffBlock_monotone _ _ _ _ _ _ _ _ h
      have hp₂ := readDynamicCodes_pos hd
      exact ⟨Nat.le_trans hp₂.1 hp.2.2, hp.2.1.trans hp₂.2⟩

/-- The outer loop spends a fuel unit only after a header consumes three bits. -/
theorem decodeFuelLoop_fuel_sufficient (bs : ByteArray) (limit fuel : Nat)
    (r : BitReader) (out : Array UInt8) (hb : r.bytes = bs)
    (hf : r.size - r.pos < fuel) :
    decodeFuelLoop bs limit r out fuel ≠ .error .fuelExhausted := by
  induction fuel generalizing r out with
  | zero => omega
  | succ fuel ih =>
    unfold decodeFuelLoop
    apply bind_never_exhausts _ _ (readHeader_never_exhausts _)
    rintro ⟨h, r₁⟩ hh
    have hb₁ := readHeader_bytes hh
    apply bind_never_exhausts _ _ (decodeBlockBody_never_exhausts _ _ _ _ _ (hb₁.trans hb))
    rintro ⟨o, r₂⟩ hd
    dsimp only
    split
    · simp
    · split
      · simp
      · have hp := readHeader_pos hh
        have hlt := readHeader_starts_lt hh
        have hp₂ := decodeBlockBody_pos hd
        apply ih _ _ (hp₂.2.trans (hb₁.trans hb))
        simp only [BitReader.size, hp₂.2, hb₁] at *
        dsimp [BitPos] at *
        omega

/-- Decoder fuel is sufficient for arbitrary byte arrays, including malformed input. -/
theorem decode_never_exhausts (bs : ByteArray) (limit : Nat) :
    decode bs limit ≠ .error .fuelExhausted := by
  apply decodeFuelLoop_fuel_sufficient bs limit (8 * bs.size + 1) ⟨bs, 0⟩ #[] rfl
  simp only [BitReader.size, Nat.sub_zero]
  omega

end Deflate
