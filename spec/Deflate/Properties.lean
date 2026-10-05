/-
  Deflate.Properties — the proof obligations of spec §9, as theorems about
  the model in `spec/Deflate/`. Nothing here is a statement about the Rust
  code. See `docs/verification-boundary.md`.
-/
import Deflate.Bitstream
import Deflate.Block
import Deflate.Huffman
import Deflate.LZ77

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
theorem fixedLitLen_valid : Code.isValid fixedLitLen = true := by decide

theorem fixedDist_valid : Code.isValid fixedDist = true := by decide

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

/-- An over-subscribed code is rejected, with no appeal to the decoder. -/
theorem oversubscribed_invalid (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isValid c = false := by simp [Code.isValid, h]

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

end Deflate
