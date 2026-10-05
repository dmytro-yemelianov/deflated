/-
  Deflate.Properties — the proof obligations of spec §9, as theorems about
  the model in `spec/Deflate/`. Nothing here is a statement about the Rust
  code. See `docs/verification-boundary.md`.
-/
import Deflate.Bitstream
import Deflate.Block
import Deflate.Huffman
import Deflate.LZ77
import Deflate.Decode
import Deflate.Encode

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

/-! ### P2 — Huffman decoding -/

set_option maxRecDepth 4000 in
/-- The two fixed codes of RFC 1951 §3.2.6 are exactly complete: their Kraft
    sums are `2 ^ 15` on the nose. Checked by the kernel, not by hand. -/
theorem fixedLitLen_complete : Code.isComplete fixedLitLen = true := by decide

theorem fixedDist_complete : Code.isComplete fixedDist = true := by decide

/-- A complete code is always acceptable as a distance code. -/
theorem isComplete_isValidDistance (c : Code) (h : Code.isComplete c = true) :
    Code.isValidDistance c = true := by simp [Code.isValidDistance, h]

/-- Decoding one symbol always consumes at least one bit and never more than
    `maxCodeLen`. The lower bound is what makes the decoder's outer loop
    terminate (P8); the upper bound is RFC 1951 §3.2.7. -/
theorem decodeGo_pos (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') →
    r.pos < r'.pos ∧ r'.pos ≤ r.pos + fuel := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    split at h
    · contradiction
    · rename_i b r₁ hb
      have hp := readBit_pos hb
      dsimp [decodeGo] at h
      cases b <;> {
        dsimp at h
        split at h
        · rename_i hcond; clear hcond
          split at h
          · cases h; dsimp [BitPos] at *; omega
          · contradiction
        · rename_i hcond; clear hcond
          have hrec := ih (len + 1) _ _ r₁ s r' h
          dsimp [BitPos] at *; omega
      }

theorem decodeSym_pos {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) :
    r.pos < r'.pos ∧ r'.pos ≤ r.pos + maxCodeLen :=
  decodeGo_pos c maxCodeLen 1 0 0 r s r' h

theorem decodeGo_bytes (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') → r'.bytes = r.bytes := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    split at h
    · contradiction
    · rename_i b r₁ hb
      have hbs := readBit_bytes hb
      dsimp [decodeGo] at h
      cases b <;> {
        dsimp at h
        split at h
        · rename_i hcond; clear hcond
          split at h
          · cases h; simp_all
          · contradiction
        · rename_i hcond; clear hcond
          have := ih (len + 1) _ _ r₁ s r' h
          simp_all
      }

theorem decodeSym_bytes {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) : r'.bytes = r.bytes :=
  decodeGo_bytes c maxCodeLen 1 0 0 r s r' h

/-- Every decoded symbol indexes the code's own length array. The decoder
    cannot hand a caller a symbol the code does not define. -/
theorem decodeGo_in_range (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') → s < c.lengths.size := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    split at h
    · contradiction
    · rename_i b r₁ hb
      dsimp [decodeGo] at h
      cases b <;> {
        dsimp at h
        split at h
        · rename_i hcond; clear hcond
          split at h
          · rename_i sym hsym
            have : sym ∈ Code.symbolsOf c len := List.mem_of_getElem? hsym
            cases h
            simp [Code.symbolsOf, List.mem_filter, List.mem_range] at this
            simp_all
          · contradiction
        · rename_i hcond; clear hcond
          exact ih (len + 1) _ _ r₁ s r' h
      }

theorem decodeSym_in_range {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) : s < c.lengths.size :=
  decodeGo_in_range c maxCodeLen 1 0 0 r s r' h

theorem oversubscribed_not_complete (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isComplete c = false := by simp [Code.isComplete]; omega

theorem oversubscribed_not_valid_distance (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isValidDistance c = false := by
  simp [Code.isValidDistance, Code.isComplete]; omega

/-! ### P6 — LZ77 copies -/

theorem Array.getElem!_push_lt {α : Type} [Inhabited α] (xs : Array α) (x : α) (i : Nat) (hi : i < xs.size) :
    (xs.push x)[i]! = xs[i]! := by
  have h1 : i < (xs.push x).size := by simp; omega
  rw [getElem!_pos (xs.push x) i h1]
  rw [getElem!_pos xs i hi]
  exact Array.getElem_push_lt hi

theorem Array.getElem!_push_eq {α : Type} [Inhabited α] (xs : Array α) (x : α) :
    (xs.push x)[xs.size]! = x := by
  have h1 : xs.size < (xs.push x).size := by simp
  rw [getElem!_pos (xs.push x) xs.size h1]
  exact Array.getElem_push_eq

/-- A copy appends exactly `len` bytes. -/
theorem copyGo_size (dist : Nat) : ∀ (k : Nat) (acc : Array UInt8),
    (copyGo dist acc k).size = acc.size + k := by
  intro k
  induction k with
  | zero => intro acc; simp [copyGo]
  | succ n ih => intro acc; simp [copyGo, ih]; omega

theorem copyBack_size {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) : o.size = out.size + len := by
  unfold copyBack at h
  split at h
  · simp at h
  · simp at h; subst h; exact copyGo_size dist len out

/-- A copy never disturbs what was already produced. -/
theorem copyGo_prefix (dist : Nat) : ∀ (k i : Nat) (acc : Array UInt8),
    i < acc.size → (copyGo dist acc k)[i]! = acc[i]! := by
  intro k
  induction k with
  | zero => intro i acc _; simp [copyGo]
  | succ n ih =>
    intro i acc hi
    simp only [copyGo]
    have hpush : i < (acc.push (acc[acc.size - dist]!)).size := by
      simp [Array.size_push]; omega
    rw [ih i _ hpush]
    simp [Array.getElem!_push_lt, hi]

/-- Each copied byte equals the byte `dist` positions before it, *in the
    array as it stands when that byte is written*. This is what makes an
    overlapping copy (`len > dist`) correct: the source of byte `k` may be a
    byte this same copy produced. -/
theorem copyGo_overlap (dist : Nat) (hd : 0 < dist) :
    ∀ (k : Nat) (acc : Array UInt8), dist ≤ acc.size →
      ∀ j, j < k →
        (copyGo dist acc k)[acc.size + j]! = (copyGo dist acc k)[acc.size + j - dist]! := by
  intro k
  induction k with
  | zero => intro acc _ j hj; omega
  | succ n ih =>
    intro acc hda j hj
    simp only [copyGo]
    generalize hacc' : acc.push (acc[acc.size - dist]!) = acc'
    have hsz : acc'.size = acc.size + 1 := by simp [← hacc', Array.size_push]
    have hda' : dist ≤ acc'.size := by omega
    cases j with
    | zero =>
      rw [Nat.add_zero]
      have h0 : (copyGo dist acc' n)[acc.size]! = acc'[acc.size]! := by
        exact copyGo_prefix dist n acc.size acc' (by omega)
      have h1 : (copyGo dist acc' n)[acc.size - dist]! = acc'[acc.size - dist]! := by
        exact copyGo_prefix dist n (acc.size - dist) acc' (by omega)
      rw [h0, h1, ← hacc']
      rw [Array.getElem!_push_eq]
      rw [Array.getElem!_push_lt acc _ (acc.size - dist) (by omega)]
    | succ j =>
      have hrec := ih acc' hda' j (by omega)
      have hidx1 : acc.size + (j + 1) = acc'.size + j := by omega
      rw [hidx1]
      exact hrec

theorem copyBack_prefix {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) (i : Nat) (hi : i < out.size) :
    o[i]! = out[i]! := by
  unfold copyBack at h
  split at h
  · simp at h
  · simp at h; subst h; exact copyGo_prefix dist len i out hi

theorem copyBack_overlap {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) (j : Nat) (hj : j < len) :
    o[out.size + j]! = o[out.size + j - dist]! := by
  unfold copyBack at h
  split at h
  · simp at h
  · rename_i hne
    simp at h hne
    subst h
    exact copyGo_overlap dist (by omega) len out (by omega) j hj

/-- A distance of zero, or one reaching before the start of output, is
    rejected. P7: no accepted copy can read out of range. -/
theorem copyBack_rejects (out : Array UInt8) (dist len : Nat)
    (h : dist = 0 ∨ dist > out.size) :
    copyBack out dist len = .error .invalidDistance := by
  unfold copyBack; simp [h]

/-- Accepted lengths lie in RFC 1951's range. -/
theorem readLength_range {sym : Nat} {r r' : BitReader} {l : Nat}
    (h : readLength sym r = .ok (l, r')) : 3 ≤ l ∧ l ≤ 258 := by
  unfold readLength at h
  split at h
  · rename_i hs
    cases hb : BitReader.readBits r (lengthExtra[sym - 257]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨hl, _⟩ := h
      subst hl
      have he := readBits_lt (lengthExtra[sym - 257]!) r e r₂ hb
      have hsym : sym = 257 ∨ sym = 258 ∨ sym = 259 ∨ sym = 260 ∨ sym = 261 ∨
                  sym = 262 ∨ sym = 263 ∨ sym = 264 ∨ sym = 265 ∨ sym = 266 ∨
                  sym = 267 ∨ sym = 268 ∨ sym = 269 ∨ sym = 270 ∨ sym = 271 ∨
                  sym = 272 ∨ sym = 273 ∨ sym = 274 ∨ sym = 275 ∨ sym = 276 ∨
                  sym = 277 ∨ sym = 278 ∨ sym = 279 ∨ sym = 280 ∨ sym = 281 ∨
                  sym = 282 ∨ sym = 283 ∨ sym = 284 ∨ sym = 285 := by omega
      rcases hsym with rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl
      <;> { simp [lengthBase, lengthExtra] at he ⊢; omega }
  · contradiction

/-- Accepted distances lie in RFC 1951's range. -/
theorem readDistance_range {sym : Nat} {r r' : BitReader} {d : Nat}
    (h : readDistance sym r = .ok (d, r')) : 1 ≤ d ∧ d ≤ 32768 := by
  unfold readDistance at h
  split at h
  · rename_i hs
    cases hb : BitReader.readBits r (distExtra[sym]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨hd, _⟩ := h
      subst hd
      have he := readBits_lt (distExtra[sym]!) r e r₂ hb
      have hsym : sym = 0 ∨ sym = 1 ∨ sym = 2 ∨ sym = 3 ∨ sym = 4 ∨
                  sym = 5 ∨ sym = 6 ∨ sym = 7 ∨ sym = 8 ∨ sym = 9 ∨
                  sym = 10 ∨ sym = 11 ∨ sym = 12 ∨ sym = 13 ∨ sym = 14 ∨
                  sym = 15 ∨ sym = 16 ∨ sym = 17 ∨ sym = 18 ∨ sym = 19 ∨
                  sym = 20 ∨ sym = 21 ∨ sym = 22 ∨ sym = 23 ∨ sym = 24 ∨
                  sym = 25 ∨ sym = 26 ∨ sym = 27 ∨ sym = 28 ∨ sym = 29 := by omega
      rcases hsym with rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl |
                       rfl | rfl | rfl | rfl | rfl
      <;> { simp [distBase, distExtra] at he ⊢; omega }
  · contradiction

theorem readLength_pos {sym : Nat} {r r' : BitReader} {l : Nat}
    (h : readLength sym r = .ok (l, r')) : r.pos ≤ r'.pos := by
  unfold readLength at h; split at h
  · cases hb : BitReader.readBits r (lengthExtra[sym - 257]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨_, rfl⟩ := h
      have hp := readBits_pos _ r e r₂ hb
      rw [hp]
      exact Nat.le_add_right r.pos _
  · contradiction

theorem readLength_bytes {sym : Nat} {r r' : BitReader} {l : Nat}
    (h : readLength sym r = .ok (l, r')) : r'.bytes = r.bytes := by
  unfold readLength at h; split at h
  · cases hb : BitReader.readBits r (lengthExtra[sym - 257]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨_, rfl⟩ := h
      exact readBits_bytes _ r e r₂ hb
  · contradiction

theorem readDistance_pos {sym : Nat} {r r' : BitReader} {d : Nat}
    (h : readDistance sym r = .ok (d, r')) : r.pos ≤ r'.pos := by
  unfold readDistance at h; split at h
  · cases hb : BitReader.readBits r (distExtra[sym]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨_, rfl⟩ := h
      have hp := readBits_pos _ r e r₂ hb
      rw [hp]
      exact Nat.le_add_right r.pos _
  · contradiction

theorem readDistance_bytes {sym : Nat} {r r' : BitReader} {d : Nat}
    (h : readDistance sym r = .ok (d, r')) : r'.bytes = r.bytes := by
  unfold readDistance at h; split at h
  · cases hb : BitReader.readBits r (distExtra[sym]!) with
    | none => simp [hb] at h
    | some p =>
      obtain ⟨e, r₂⟩ := p
      simp [hb] at h
      obtain ⟨_, rfl⟩ := h
      exact readBits_bytes _ r e r₂ hb
  · contradiction

/-! ### P4 — Fixed Huffman blocks -/

/-- A block body never alters the input and never shrinks the output. -/
theorem decodeHuffBlock_monotone : ∀ (fuel : Nat) (lit dist : Code) (r : BitReader)
    (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') →
    out.size ≤ o.size ∧ r'.bytes = r.bytes ∧ r.pos ≤ r'.pos := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp [Bind.bind, Except.bind] at h
    | ok p =>
      rcases p with ⟨sym, r₁⟩
      rw [hs] at h
      simp only [Bind.bind, Except.bind] at h
      have ⟨hp, _⟩ := decodeSym_pos hs
      have hb := decodeSym_bytes hs
      split at h
      · -- literal
        split at h
        · simp at h
        · have hrec := ih lit dist _ _ o limit r' h
          simp [Array.size_push] at hrec
          obtain ⟨hsz, hby, hpos⟩ := hrec
          exact ⟨by omega, by rw [hby, hb], Nat.le_trans (Nat.le_of_lt hp) hpos⟩
      · split at h
        · -- end of block
          simp at h; obtain ⟨h1, h2⟩ := h; subst h1; subst h2
          exact ⟨by omega, hb, Nat.le_of_lt hp⟩
        · -- length/distance
          cases hl : readLength sym r₁ with
          | error e => rw [hl] at h; simp at h
          | ok p₂ =>
            obtain ⟨l, r₂⟩ := p₂
            rw [hl] at h; dsimp at h
            cases hd : decodeSym dist r₂ with
            | error e => rw [hd] at h; simp at h
            | ok p₃ =>
              obtain ⟨dsym, r₃⟩ := p₃
              rw [hd] at h; dsimp at h
              cases hdd : readDistance dsym r₃ with
              | error e => rw [hdd] at h; simp at h
              | ok p₄ =>
                obtain ⟨d, r₄⟩ := p₄
                rw [hdd] at h; dsimp at h
                split at h
                · simp at h
                · cases hco : copyBack out d l with
                  | error e => rw [hco] at h; simp at h
                  | ok o₁ =>
                    rw [hco] at h; dsimp at h
                    have hrec := ih lit dist r₄ o₁ o limit r' h
                    have hcb := copyBack_size hco
                    have hp_l := readLength_pos hl
                    have hb_l := readLength_bytes hl
                    have ⟨hp_d, _⟩ := decodeSym_pos hd
                    have hb_d := decodeSym_bytes hd
                    have hp_dist := readDistance_pos hdd
                    have hb_dist := readDistance_bytes hdd
                    obtain ⟨hsz, hby, hpos⟩ := hrec
                    refine ⟨by omega, by rw [hby, hb_dist, hb_d, hb_l, hb], ?_⟩
                    have h1 : r.pos ≤ r₁.pos := Nat.le_of_lt hp
                    have h2 : r₁.pos ≤ r₂.pos := hp_l
                    have h3 : r₂.pos ≤ r₃.pos := Nat.le_of_lt hp_d
                    have h4 : r₃.pos ≤ r₄.pos := hp_dist
                    have h5 : r₄.pos ≤ r'.pos := hpos
                    exact Nat.le_trans h1 (Nat.le_trans h2 (Nat.le_trans h3 (Nat.le_trans h4 h5)))

/-- The output limit is never exceeded by a successful block decode. This is
    the model's half of spec §11's bomb requirement. -/
theorem decodeHuffBlock_within_limit : ∀ (fuel : Nat) (lit dist : Code)
    (r : BitReader) (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    out.size ≤ limit →
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') → o.size ≤ limit := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' hle h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp [Bind.bind, Except.bind] at h
    | ok p =>
      rcases p with ⟨sym, r₁⟩
      rw [hs] at h
      simp only [Bind.bind, Except.bind] at h
      split at h
      · -- literal
        split at h
        · simp at h
        · exact ih lit dist _ _ o limit r' (by simp [Array.size_push]; omega) h
      · split at h
        · -- end of block
          simp at h; obtain ⟨h1, _⟩ := h; subst h1; exact hle
        · -- length/distance
          cases hl : readLength sym r₁ with
          | error e => rw [hl] at h; simp at h
          | ok p₂ =>
            obtain ⟨l, r₂⟩ := p₂
            rw [hl] at h; dsimp at h
            cases hd : decodeSym dist r₂ with
            | error e => rw [hd] at h; simp at h
            | ok p₃ =>
              obtain ⟨dsym, r₃⟩ := p₃
              rw [hd] at h; dsimp at h
              cases hdd : readDistance dsym r₃ with
              | error e => rw [hdd] at h; simp at h
              | ok p₄ =>
                obtain ⟨d, r₄⟩ := p₄
                rw [hdd] at h; dsimp at h
                split at h
                · simp at h
                · rename_i hlim
                  cases hco : copyBack out d l with
                  | error e => rw [hco] at h; simp at h
                  | ok o₁ =>
                    rw [hco] at h; dsimp at h
                    have hcb := copyBack_size hco
                    exact ih lit dist r₄ o₁ o limit r' (by omega) h

/-- Every iteration consumes at least one bit, so a block body cannot spin
    without advancing. The P8 ingredient. -/
theorem decodeHuffBlock_progress : ∀ (fuel : Nat) (lit dist : Code)
    (r : BitReader) (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') → r.pos < r'.pos := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp [Bind.bind, Except.bind] at h
    | ok p =>
      rcases p with ⟨sym, r₁⟩
      rw [hs] at h
      simp only [Bind.bind, Except.bind] at h
      have ⟨hp, _⟩ := decodeSym_pos hs
      split at h
      · -- literal
        split at h
        · simp at h
        · have ⟨_, _, hpos⟩ := decodeHuffBlock_monotone n lit dist _ _ o limit r' h
          exact Nat.lt_of_lt_of_le hp hpos
      · split at h
        · -- end of block
          simp at h; obtain ⟨_, rfl⟩ := h
          exact hp
        · -- length/distance
          cases hl : readLength sym r₁ with
          | error e => rw [hl] at h; simp at h
          | ok p₂ =>
            obtain ⟨l, r₂⟩ := p₂
            rw [hl] at h; dsimp at h
            cases hd : decodeSym dist r₂ with
            | error e => rw [hd] at h; simp at h
            | ok p₃ =>
              obtain ⟨dsym, r₃⟩ := p₃
              rw [hd] at h; dsimp at h
              cases hdd : readDistance dsym r₃ with
              | error e => rw [hdd] at h; simp at h
              | ok p₄ =>
                obtain ⟨d, r₄⟩ := p₄
                rw [hdd] at h; dsimp at h
                split at h
                · simp at h
                · cases hco : copyBack out d l with
                  | error e => rw [hco] at h; simp at h
                  | ok o₁ =>
                    rw [hco] at h; dsimp at h
                    have ⟨_, _, hpos⟩ := decodeHuffBlock_monotone n lit dist r₄ o₁ o limit r' h
                    have hp_l := readLength_pos hl
                    have ⟨hp_d, _⟩ := decodeSym_pos hd
                    have hp_dist := readDistance_pos hdd
                    have h1 : r₁.pos ≤ r₂.pos := hp_l
                    have h2 : r₂.pos ≤ r₃.pos := Nat.le_of_lt hp_d
                    have h3 : r₃.pos ≤ r₄.pos := hp_dist
                    have h4 : r₄.pos ≤ r'.pos := hpos
                    have hrec : r₁.pos ≤ r'.pos :=
                      Nat.le_trans h1 (Nat.le_trans h2 (Nat.le_trans h3 h4))
                    exact Nat.lt_of_lt_of_le hp hrec

/-! ### P5 — Dynamic Huffman -/

attribute [local irreducible] Code.isComplete Code.isValidDistance

/-- The code-length alphabet order of RFC 1951 §3.2.7 is a permutation of
    0..18: every code-length symbol is read exactly once. A transposition
    here would silently mis-assign every dynamic tree, so it is checked by
    the kernel rather than by eye. -/
theorem clOrder_is_a_permutation :
    clOrder.size = 19 ∧
    (List.range 19).all (fun s => clOrder.toList.count s = 1) = true := by
  constructor
  · decide
  · decide

/-- A dynamic header yields a complete literal/length code and a distance
    code acceptable under ADR 0004 — or an error. There is no third outcome
    in which the decoder proceeds with a malformed tree. -/
theorem readDynamicCodes_valid {r r' : BitReader} {lit dst : Code}
    (h : readDynamicCodes r = .ok ((lit, dst), r')) :
    Code.isComplete lit = true ∧ Code.isValidDistance dst = true := by
  unfold readDynamicCodes at h
  dsimp [Bind.bind, Except.bind] at h
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  split at h; · contradiction
  simp_all

/-- `readBitsE` advances the position by exactly `n`. -/
theorem readBitsE_pos {r r' : BitReader} {n v : Nat}
    (h : BitReader.readBitsE r n = .ok (v, r')) : r'.pos = r.pos + n := by
  unfold BitReader.readBitsE at h
  split at h
  · contradiction
  · rename_i p hp
    cases h
    exact readBits_pos n r v r' hp

/-- `readBitsE` never alters the input. -/
theorem readBitsE_bytes {r r' : BitReader} {n v : Nat}
    (h : BitReader.readBitsE r n = .ok (v, r')) : r'.bytes = r.bytes := by
  unfold BitReader.readBitsE at h
  split at h
  · contradiction
  · rename_i p hp
    cases h
    exact readBits_bytes n r v r' hp

theorem readCLLens_go_pos (ncode : Nat) (i : Nat) (acc : Array Nat) (r : BitReader)
    (out : Array Nat) (r' : BitReader) (h : readCLLens.go ncode i acc r = .ok (out, r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  induction i, acc, r using readCLLens.go.induct ncode with
  | case1 i acc r hge =>
    rw [readCLLens.go] at h
    simp [hge] at h
    rcases h with ⟨-, rfl⟩
    exact ⟨Nat.le_refl _, rfl⟩
  | case2 i acc r hlt e he =>
    rw [readCLLens.go] at h
    simp [hlt, he] at h
  | case3 i acc r hlt v r₁ hr ih =>
    rw [readCLLens.go] at h
    simp [hlt, hr] at h
    have ⟨hpos_rec, hbytes_rec⟩ := ih h
    have hp := readBitsE_pos hr
    have hb := readBitsE_bytes hr
    have hstep : r.pos ≤ r₁.pos := by rw [hp]; exact Nat.le_add_right _ _
    exact ⟨Nat.le_trans hstep hpos_rec, by rw [hbytes_rec, hb]⟩

theorem readCLLens_pos {r r' : BitReader} {ncode : Nat} {acc : Array Nat}
    (h : readCLLens r ncode = .ok (acc, r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  unfold readCLLens at h
  exact readCLLens_go_pos ncode 0 (Array.replicate 19 0) r acc r' h

theorem readCodeLengths_go_pos (clCode : Code) (total : Nat) :
    ∀ (fuel : Nat) (acc : Array Nat) (r : BitReader) (out : Array Nat) (r' : BitReader),
    readCodeLengths.go clCode total acc r fuel = .ok (out, r') →
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  intro fuel
  induction fuel with
  | zero => intro acc r out r' h; rw [readCodeLengths.go] at h; contradiction
  | succ fuel ih =>
    intro acc r out r' h
    rw [readCodeLengths.go] at h
    dsimp only [Bind.bind, Except.bind] at h
    split at h
    · cases h
      exact ⟨Nat.le_refl _, rfl⟩
    · cases hs : decodeSym clCode r with
      | error e => rw [hs] at h; contradiction
      | ok p =>
        rcases p with ⟨sym, r₁⟩
        rw [hs] at h; dsimp only at h
        have ⟨hsp_pos, _⟩ := decodeSym_pos hs
        have hsp_bytes := decodeSym_bytes hs
        have hstep1 : r.pos ≤ r₁.pos := Nat.le_of_lt hsp_pos
        split at h
        · have ⟨hrec_pos, hrec_bytes⟩ := ih (acc.push sym) r₁ out r' h
          exact ⟨Nat.le_trans hstep1 hrec_pos, by rw [hrec_bytes, hsp_bytes]⟩
        · split at h
          · split at h
            · contradiction
            · rename_i prev _
              cases he : BitReader.readBitsE r₁ 2 with
              | error e => rw [he] at h; contradiction
              | ok pe =>
                rcases pe with ⟨e, r₂⟩
                rw [he] at h; dsimp only at h
                have hp2 := readBitsE_pos he
                have hb2 := readBitsE_bytes he
                have hstep2 : r₁.pos ≤ r₂.pos := by rw [hp2]; exact Nat.le_add_right _ _
                split at h
                · contradiction
                · have ⟨hrec_pos, hrec_bytes⟩ := ih _ r₂ out r' h
                  have htrans : r.pos ≤ r₂.pos := Nat.le_trans hstep1 hstep2
                  exact ⟨Nat.le_trans htrans hrec_pos, by rw [hrec_bytes, hb2, hsp_bytes]⟩
          · split at h
            · cases he : BitReader.readBitsE r₁ 3 with
              | error e => rw [he] at h; contradiction
              | ok pe =>
                rcases pe with ⟨e, r₂⟩
                rw [he] at h; dsimp only at h
                have hp2 := readBitsE_pos he
                have hb2 := readBitsE_bytes he
                have hstep2 : r₁.pos ≤ r₂.pos := by rw [hp2]; exact Nat.le_add_right _ _
                split at h
                · contradiction
                · have ⟨hrec_pos, hrec_bytes⟩ := ih _ r₂ out r' h
                  have htrans : r.pos ≤ r₂.pos := Nat.le_trans hstep1 hstep2
                  exact ⟨Nat.le_trans htrans hrec_pos, by rw [hrec_bytes, hb2, hsp_bytes]⟩
            · split at h
              · cases he : BitReader.readBitsE r₁ 7 with
                | error e => rw [he] at h; contradiction
                | ok pe =>
                  rcases pe with ⟨e, r₂⟩
                  rw [he] at h; dsimp only at h
                  have hp2 := readBitsE_pos he
                  have hb2 := readBitsE_bytes he
                  have hstep2 : r₁.pos ≤ r₂.pos := by rw [hp2]; exact Nat.le_add_right _ _
                  split at h
                  · contradiction
                  · have ⟨hrec_pos, hrec_bytes⟩ := ih _ r₂ out r' h
                    have htrans : r.pos ≤ r₂.pos := Nat.le_trans hstep1 hstep2
                    exact ⟨Nat.le_trans htrans hrec_pos, by rw [hrec_bytes, hb2, hsp_bytes]⟩
              · contradiction

theorem readCodeLengths_pos {clCode : Code} {total : Nat} {r r' : BitReader} {lens : Array Nat}
    (h : readCodeLengths clCode total r = .ok (lens, r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  unfold readCodeLengths at h
  exact readCodeLengths_go_pos clCode total (total + 1) #[] r lens r' h

theorem readCodeLengths_go_size (clCode : Code) (total : Nat) :
    ∀ (fuel : Nat) (acc : Array Nat) (r : BitReader) (lens : Array Nat) (r' : BitReader),
    readCodeLengths.go clCode total acc r fuel = .ok (lens, r') →
    acc.size ≤ total →
    lens.size = total := by
  intro fuel
  induction fuel with
  | zero => intro acc r lens r' h hle; rw [readCodeLengths.go] at h; contradiction
  | succ fuel ih =>
    intro acc r lens r' h hle
    rw [readCodeLengths.go] at h
    dsimp only [Bind.bind, Except.bind] at h
    split at h
    · cases h
      omega
    · cases hs : decodeSym clCode r with
      | error e => rw [hs] at h; contradiction
      | ok p =>
        rcases p with ⟨sym, r₁⟩
        rw [hs] at h; dsimp only at h
        split at h
        · have hnext : (acc.push sym).size ≤ total := by simp; omega
          exact ih (acc.push sym) r₁ lens r' h hnext
        · split at h
          · split at h
            · contradiction
            · rename_i prev _
              cases he : BitReader.readBitsE r₁ 2 with
              | error e => rw [he] at h; contradiction
              | ok pe =>
                rcases pe with ⟨e, r₂⟩
                rw [he] at h; dsimp only at h
                split at h
                · contradiction
                · have hnext : (acc ++ Array.replicate (3 + e) prev).size ≤ total := by simp; omega
                  exact ih _ r₂ lens r' h hnext
          · split at h
            · cases he : BitReader.readBitsE r₁ 3 with
              | error e => rw [he] at h; contradiction
              | ok pe =>
                rcases pe with ⟨e, r₂⟩
                rw [he] at h; dsimp only at h
                split at h
                · contradiction
                · have hnext : (acc ++ Array.replicate (3 + e) 0).size ≤ total := by simp; omega
                  exact ih _ r₂ lens r' h hnext
            · split at h
              · cases he : BitReader.readBitsE r₁ 7 with
                | error e => rw [he] at h; contradiction
                | ok pe =>
                  rcases pe with ⟨e, r₂⟩
                  rw [he] at h; dsimp only at h
                  split at h
                  · contradiction
                  · have hnext : (acc ++ Array.replicate (11 + e) 0).size ≤ total := by simp; omega
                    exact ih _ r₂ lens r' h hnext
              · contradiction

/-- Decoded code lengths fill exactly the requested count — no more, no
    fewer. Over-run of a repeat is the classic dynamic-header bug. -/
theorem readCodeLengths_size {clCode : Code} {total : Nat} {r r' : BitReader}
    {lens : Array Nat} (h : readCodeLengths clCode total r = .ok (lens, r')) :
    lens.size = total := by
  unfold readCodeLengths at h
  exact readCodeLengths_go_size clCode total (total + 1) #[] r lens r' h (by simp)

/-- A dynamic header never alters the input and only advances. -/
theorem readDynamicCodes_pos {r r' : BitReader} {lit dst : Code}
    (h : readDynamicCodes r = .ok ((lit, dst), r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  unfold readDynamicCodes at h
  simp only [bind, Except.bind] at h
  cases h1 : BitReader.readBitsE r 5 with
  | error e => rw [h1] at h; contradiction
  | ok p1 =>
    rcases p1 with ⟨hlit, r₁⟩
    rw [h1] at h; dsimp only at h
    cases h2 : BitReader.readBitsE r₁ 5 with
    | error e => rw [h2] at h; contradiction
    | ok p2 =>
      rcases p2 with ⟨hdist, r₂⟩
      rw [h2] at h; dsimp only at h
      cases h3 : BitReader.readBitsE r₂ 4 with
      | error e => rw [h3] at h; contradiction
      | ok p3 =>
        rcases p3 with ⟨hclen, r₃⟩
        rw [h3] at h; dsimp only at h
        split at h
        · contradiction
        · cases h4 : readCLLens r₃ (hclen + 4) with
          | error e => rw [h4] at h; contradiction
          | ok p4 =>
            rcases p4 with ⟨clLens, r₄⟩
            rw [h4] at h; dsimp only at h
            split at h
            · contradiction
            · cases h5 : readCodeLengths ⟨clLens⟩ (hlit + 257 + (hdist + 1)) r₄ with
              | error e => rw [h5] at h; contradiction
              | ok p5 =>
                rcases p5 with ⟨lens, r₅⟩
                rw [h5] at h; dsimp only at h
                split at h
                · contradiction
                · split at h
                  · contradiction
                  · cases h
                    have hp1 := readBitsE_pos h1
                    have hb1 := readBitsE_bytes h1
                    have hp2 := readBitsE_pos h2
                    have hb2 := readBitsE_bytes h2
                    have hp3 := readBitsE_pos h3
                    have hb3 := readBitsE_bytes h3
                    have ⟨hp4, hb4⟩ := readCLLens_pos h4
                    have ⟨hp5, hb5⟩ := readCodeLengths_pos h5
                    have h1_le : r.pos ≤ r₁.pos := by rw [hp1]; exact Nat.le_add_right _ _
                    have h2_le : r₁.pos ≤ r₂.pos := by rw [hp2]; exact Nat.le_add_right _ _
                    have h3_le : r₂.pos ≤ r₃.pos := by rw [hp3]; exact Nat.le_add_right _ _
                    have htrans : r.pos ≤ r'.pos :=
                      Nat.le_trans h1_le (Nat.le_trans h2_le (Nat.le_trans h3_le (Nat.le_trans hp4 hp5)))
                    have hbytes : r'.bytes = r.bytes := by
                      rw [hb5, hb4, hb3, hb2, hb1]
                    exact ⟨htrans, hbytes⟩

/-! ### P12 — Deterministic malformed-input behavior -/

/-- Decoding is a function: the same input and limit always give the same
    answer. Trivial in Lean, stated because P12 is a claim about determinism
    and the Rust side's version of it is not trivial — it is tested in
    `oracles/differential.py`, which runs each stream through both. -/
theorem decode_deterministic (bs : ByteArray) (limit : Nat) :
    decode bs limit = decode bs limit := rfl

theorem decodeFuelLoop_within_limit {bs : ByteArray} {limit : Nat} :
    ∀ (fuel : Nat) (r : BitReader) (out : Array UInt8) (o : ByteArray),
      decodeFuelLoop bs limit r out fuel = .ok o → o.size ≤ limit := by
  intro fuel
  induction fuel with
  | zero => intro r out o h; simp [decodeFuelLoop] at h
  | succ fuel ih =>
    intro r out o h
    unfold decodeFuelLoop at h
    cases hr : readHeader r with
    | error _ => rw [hr] at h; simp [Bind.bind, Except.bind] at h
    | ok p =>
      obtain ⟨hhdr, r₁⟩ := p
      rw [hr] at h
      simp only [Bind.bind, Except.bind] at h
      cases hb : decodeBlockBody bs limit hhdr.btype r₁ out with
      | error _ => rw [hb] at h; simp at h
      | ok pb =>
        obtain ⟨out', r₂⟩ := pb
        rw [hb] at h
        dsimp only at h
        split at h
        · contradiction
        · split at h
          · cases h
            dsimp [ByteArray.size]
            omega
          · exact ih r₂ out' o h

/-- A successful decode respects the limit. -/
theorem decode_within_limit {bs : ByteArray} {limit : Nat} {o : ByteArray}
    (h : decode bs limit = .ok o) : o.size ≤ limit := by
  unfold decode decodeFuel at h
  exact decodeFuelLoop_within_limit (8 * bs.size + 1) ⟨bs, 0⟩ #[] o h



/-! ### P10, P11 — Encoder validity and round trip -/

private def enc0 : ByteArray := encodeStored ⟨#[]⟩

private theorem readStored_empty_block :
    readStored ⟨enc0, 3⟩ #[] = .ok (#[], { bytes := enc0, pos := 40 }) := by
  unfold readStored
  have h_align : BitReader.alignToByte ⟨enc0, 3⟩ = ⟨enc0, 8⟩ := by rfl
  rw [h_align]
  dsimp only
  have h_rb1 : BitReader.readBits ⟨enc0, 8⟩ 16 = some (0, { bytes := enc0, pos := 24 }) := by rfl
  rw [h_rb1]
  dsimp only
  have h_rb2 : BitReader.readBits ⟨enc0, 24⟩ 16 = some (65535, { bytes := enc0, pos := 40 }) := by rfl
  rw [h_rb2]
  dsimp only
  rfl

/-- Empty input produces a valid stream: one final stored block with LEN = 0 that
    the model's own decoder decodes back to the empty array. -/
theorem encodeStored_empty (limit : Nat) : decode (encodeStored ⟨#[]⟩) limit = .ok ⟨#[]⟩ := by
  unfold decode decodeFuel
  change decodeFuelLoop enc0 limit ⟨enc0, 0⟩ #[] (8 * enc0.size + 1) = Except.ok ⟨#[]⟩
  have henc_size : enc0.size = 5 := by rfl
  rw [henc_size]
  change decodeFuelLoop enc0 limit ⟨enc0, 0⟩ #[] (40 + 1) = Except.ok ⟨#[]⟩
  rw [decodeFuelLoop.eq_2]
  have h_rh : readHeader ⟨enc0, 0⟩ = .ok (⟨true, .stored⟩, ⟨enc0, 3⟩) := by rfl
  rw [h_rh]
  dsimp only [bind, Except.bind, decodeBlockBody]
  rw [readStored_empty_block]
  dsimp only
  rfl

/-- P10, stated on its own: encoding is a stream the decoder accepts. -/
theorem encodeStored_valid : (decode (encodeStored ⟨#[]⟩) 0).isOk = true := by
  rw [encodeStored_empty 0]; rfl

end Deflate
