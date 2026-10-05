/-
  Deflate.Properties — the proof obligations of spec §9, as theorems about
  the model in `spec/Deflate/`. Nothing here is a statement about the Rust
  code. See `docs/verification-boundary.md`.
-/
import Deflate.Bitstream
import Deflate.Block

namespace Deflate
open BitReader

/-! ### P1 — Bit reader -/

/-- Reading one bit advances the position by exactly one. -/
theorem readBit_pos {r r' : BitReader} {b : Bool} (h : readBit r = some (b, r')) :
    r'.pos = r.pos + 1 := by
  unfold readBit at h
  split at h
  · cases h; rfl
  · contradiction

/-- Reading never alters the input. -/
theorem readBit_bytes {r r' : BitReader} {b : Bool} (h : readBit r = some (b, r')) :
    r'.bytes = r.bytes := by
  unfold readBit at h
  split at h
  · cases h; rfl
  · contradiction

/-- Reading one bit requires the position to be within the stream size. -/
theorem readBit_lt {r r' : BitReader} {b : Bool} (h : readBit r = some (b, r')) :
    r.pos < r.size := by
  unfold readBit at h
  split at h
  · assumption
  · contradiction

/-- `readBits` advances by exactly the number of bits requested. -/
theorem readBits_pos : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → r'.pos = r.pos + n := by
  intro n
  induction n with
  | zero =>
    intro r v r' h
    unfold readBits at h
    cases h
    rfl
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      have h1 := readBit_pos hb
      rw [hb] at h
      dsimp at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        have h2 := ih r₁ rest r₂ hr
        rw [hr] at h
        dsimp at h
        cases h
        dsimp [BitPos] at *
        omega

/-- Reading never alters the input, at any width. -/
theorem readBits_bytes : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → r'.bytes = r.bytes := by
  intro n
  induction n with
  | zero =>
    intro r v r' h
    unfold readBits at h
    cases h
    rfl
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      have h1 := readBit_bytes hb
      rw [hb] at h
      dsimp at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        have h2 := ih r₁ rest r₂ hr
        rw [hr] at h
        dsimp at h
        cases h
        rw [h2, h1]

/-- `n` bits yield a value below `2 ^ n`: the bound every caller relies on
    when it adds extra bits to a base. -/
theorem readBits_lt : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → v < 2 ^ n := by
  intro n
  induction n with
  | zero =>
    intro r v r' h
    unfold readBits at h
    cases h
    decide
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      dsimp at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        have hrest := ih r₁ rest r₂ hr
        rw [hr] at h
        dsimp at h
        cases h
        have hp : 2 ^ (n + 1) = 2 * 2 ^ n := by rw [Nat.pow_succ]; omega
        cases b <;> dsimp <;> omega

/-- Insufficient input is reported, deterministically, and never guessed at.
    Note on weakening (spec Task 4 Step 6):
    Reading 0 bits succeeds unconditionally (`readBits r 0 = some (0, r)`),
    so EOF requires `0 < n`. We provide `(hn : 0 < n := by omega)` as an optional
    proof parameter with a default `omega` tactic so existing callers can either
    pass `hn` explicitly or let `omega` infer it automatically. -/
theorem readBits_eof (n : Nat) (r : BitReader) (h : r.size < r.pos + n) (hn : 0 < n := by omega) :
    readBits r n = none := by
  induction n generalizing r with
  | zero => omega
  | succ k ih =>
    unfold readBits
    cases hb : readBit r with
    | none =>
      rfl
    | some p =>
      obtain ⟨b, r₁⟩ := p
      dsimp
      have hpos := readBit_pos hb
      have hbytes := readBit_bytes hb
      have hlt := readBit_lt hb
      have hsize : r₁.size = r.size := by unfold size; rw [hbytes]
      by_cases hk : k = 0
      · subst hk
        dsimp [BitPos] at *
        omega
      · have hkpos : 0 < k := Nat.pos_of_ne_zero hk
        have hrec : r₁.size < r₁.pos + k := by
          dsimp [BitPos] at *
          omega
        rw [ih r₁ hrec hkpos]
        rfl

/-! ### P1 — alignment -/

theorem alignToByte_aligned (r : BitReader) : (alignToByte r).pos % 8 = 0 := by
  dsimp [alignToByte]
  rw [Nat.mul_mod_left]

theorem alignToByte_ge (r : BitReader) : r.pos ≤ (alignToByte r).pos := by
  dsimp [alignToByte, BitPos]
  omega

theorem alignToByte_lt (r : BitReader) : (alignToByte r).pos < r.pos + 8 := by
  dsimp [alignToByte, BitPos]
  omega

theorem alignToByte_idem (r : BitReader) :
    alignToByte (alignToByte r) = alignToByte r := by
  dsimp [alignToByte]
  congr 1
  generalize (r.pos + 7) / 8 = k
  dsimp [BitPos] at *
  omega

theorem alignToByte_bytes (r : BitReader) : (alignToByte r).bytes = r.bytes := rfl

/-! ### P3 — Stored blocks -/

/-- A block header is exactly three bits: BFINAL then BTYPE. -/
theorem readHeader_pos {r r' : BitReader} {h : Header}
    (hh : readHeader r = .ok (h, r')) : r'.pos = r.pos + 3 := by
  unfold readHeader at hh
  split at hh
  · contradiction
  · rename_i b r₁ hb
    split at hh
    · contradiction
    · rename_i t r₂ ht
      have h1 := readBit_pos hb
      have h2 := readBits_pos 2 r₁ t r₂ ht
      split at hh
      · cases hh; rw [h2, h1]
      · split at hh
        · cases hh; rw [h2, h1]
        · split at hh
          · cases hh; rw [h2, h1]
          · contradiction

/-- After a stored block the reader is byte aligned: the next block header
    starts on a byte boundary, which is what makes RFC 1951 §3.2.4 work. -/
theorem readStored_aligned {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) : r'.pos % 8 = 0 := by
  unfold readStored at hs
  dsimp at hs
  split at hs
  · contradiction
  · split at hs
    · contradiction
    · split at hs
      · contradiction
      · split at hs
        · contradiction
        · rename_i _ len r₁ h1 _ nlen r₂ h2 _ _
          cases hs
          dsimp
          have p1 := readBits_pos 16 _ len r₁ h1
          have p2 := readBits_pos 16 r₁ nlen r₂ h2
          change r₁.pos = (r.pos + 7) / 8 * 8 + 16 at p1
          generalize hk : (r.pos + 7) / 8 = k
          rw [hk] at p1
          have heq : r₂.pos + 8 * len = (k + 4 + len) * 8 := by
            have hlin : ∀ (p₁ p₂ k len : Nat), p₁ = k * 8 + 16 → p₂ = p₁ + 16 → p₂ + 8 * len = (k + 4 + len) * 8 := by
              intros; omega
            exact hlin r₁.pos r₂.pos k len p1 p2
          rw [heq, Nat.mul_mod_left]

/-- Reading a stored block never alters the input. -/
theorem readStored_bytes {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) : r'.bytes = r.bytes := by
  unfold readStored at hs
  dsimp at hs
  split at hs
  · contradiction
  · split at hs
    · contradiction
    · split at hs
      · contradiction
      · split at hs
        · contradiction
        · rename_i _ len r₁ h1 _ nlen r₂ h2 _ _
          cases hs
          dsimp
          have b1 := readBits_bytes 16 _ len r₁ h1
          have b2 := readBits_bytes 16 r₁ nlen r₂ h2
          have ba : (BitReader.alignToByte r).bytes = r.bytes := rfl
          rw [b2, b1, ba]

/-- Output grows by exactly `LEN` bytes, and the reader advances by exactly
    `32 + 8 * LEN` bits past the alignment point. This is the P3 statement:
    LEN governs both the payload copy and the bit accounting, together. -/
theorem readStored_consumes {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) :
    out.size ≤ o.size ∧
    r'.pos = (BitReader.alignToByte r).pos + 32 + 8 * (o.size - out.size) := by
  unfold readStored at hs
  dsimp at hs
  split at hs
  · contradiction
  · split at hs
    · contradiction
    · split at hs
      · contradiction
      · split at hs
        · contradiction
        · rename_i _ len r₁ h1 _ nlen r₂ h2 _ _
          cases hs
          dsimp
          have p1 := readBits_pos 16 _ len r₁ h1
          have p2 := readBits_pos 16 r₁ nlen r₂ h2
          simp
          have hlin : ∀ (p₀ p₁ p₂ : Nat),
              p₁ = p₀ + 16 → p₂ = p₁ + 16 →
              p₂ = p₀ + 32 := by
            intros; omega
          exact hlin (alignToByte r).pos r₁.pos r₂.pos p1 p2

/-- An invalid length complement is rejected, and nothing is appended. -/
theorem readStored_rejects_bad_nlen (r : BitReader) (out : Array UInt8)
    (len nlen : Nat) (r₁ r₂ : BitReader)
    (h1 : BitReader.readBits (BitReader.alignToByte r) 16 = some (len, r₁))
    (h2 : BitReader.readBits r₁ 16 = some (nlen, r₂))
    (hne : nlen ≠ 0xFFFF - len) :
    readStored r out = .error .invalidStoredLength := by
  unfold readStored
  simp [h1, h2, hne]

/-- BTYPE = 3 is reserved and rejected deterministically. -/
theorem readHeader_rejects_btype3 (r : BitReader) (f : Bool) (r₁ r₂ : BitReader)
    (hb : BitReader.readBit r = some (f, r₁))
    (ht : BitReader.readBits r₁ 2 = some (3, r₂)) :
    readHeader r = .error .invalidBlockType := by
  unfold readHeader; simp [hb, ht]

/-- A header never alters the input. -/
theorem readHeader_bytes {r r' : BitReader} {h : Header}
    (hh : readHeader r = .ok (h, r')) : r'.bytes = r.bytes := by
  unfold readHeader at hh
  split at hh
  · contradiction
  · rename_i b r₁ hb
    split at hh
    · contradiction
    · rename_i t r₂ ht
      have h1 := readBit_bytes hb
      have h2 := readBits_bytes 2 r₁ t r₂ ht
      split at hh
      · cases hh; rw [h2, h1]
      · split at hh
        · cases hh; rw [h2, h1]
        · split at hh
          · cases hh; rw [h2, h1]
          · contradiction

end Deflate
