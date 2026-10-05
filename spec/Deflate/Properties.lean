/-
  Deflate.Properties — the proof obligations of spec §9, as theorems about
  the model in `spec/Deflate/`. Nothing here is a statement about the Rust
  code. See `docs/verification-boundary.md`.
-/
import Deflate.Bitstream
import Deflate.Block
import Deflate.Huffman
import Deflate.HuffmanTable
import Deflate.Canonical
import Deflate.LZ77
import Deflate.Match
import Deflate.BitWriter
import Deflate.Decode
import Deflate.Encode
import Deflate.EncodeFixed
import Deflate.Compress

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

/-! ### P2 — Table-driven Huffman decoding (ADR 0005) -/

private theorem and_one_beq_testBit (x j : Nat) : ((x >>> j) &&& 1 == 1) = x.testBit j := by
  rw [Nat.testBit, Nat.and_one_is_mod, Nat.one_and_eq_mod_two]
  rcases Nat.mod_two_eq_zero_or_one (x >>> j) with h | h <;> simp [h]

/-- `bitAt` is a `testBit` on the byte holding the bit. -/
theorem bitAt_eq_testBit (bs : ByteArray) (i : Nat) :
    bitAt bs i = (byteAt bs (i / 8)).toNat.testBit (i % 8) := by
  unfold bitAt; exact and_one_beq_testBit _ _

/-- What `readBits` returns, bit by bit: value bit `i` is stream bit
    `pos + i`, and that bit lies inside the stream. This is the sense in which
    the fast path's peeked pattern is "the next `tableBits` bits". -/
theorem readBits_bit : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') →
    ∀ i < n, r.pos + i < r.size ∧ bitAt r.bytes (r.pos + i) = v.testBit i := by
  intro n
  induction n with
  | zero => intro _ _ _ _ i hi; omega
  | succ n ih =>
    intro r v r' h i hi
    simp only [readBits, Option.bind_eq_bind, Option.bind_eq_some_iff] at h
    obtain ⟨⟨b, r₁⟩, hb, ⟨rest, r₂⟩, hrest, hv⟩ := h
    simp only [Option.pure_def, Option.some.injEq, Prod.mk.injEq] at hv
    obtain ⟨rfl, rfl⟩ := hv
    have hp := readBit_pos hb
    have hbs := readBit_bytes hb
    have hlt := readBit_lt hb
    have hbit : b = bitAt r.bytes r.pos := by
      unfold readBit at hb; split at hb
      · cases hb; rfl
      · contradiction
    have hsz : r₁.size = r.size := by simp [BitReader.size, hbs]
    cases i with
    | zero => subst hbit; cases hb' : bitAt r.bytes r.pos <;> simp_all
    | succ j =>
      have := ih r₁ rest r₂ hrest j (by omega)
      rw [hsz, hbs, hp] at this
      obtain ⟨h1, h2⟩ := this
      dsimp only [BitPos] at *
      refine ⟨by omega, ?_⟩
      rw [show (r.pos : Nat) + (j + 1) = r.pos + 1 + j by rw [Nat.add_assoc, Nat.add_comm 1 j], h2, Nat.testBit_succ]
      congr 1
      cases b <;> simp <;> omega

/-- The pattern stream holds 16 bits, more than `tableBits`. -/
theorem patternReader_size (p : Nat) : (patternReader p).size = 16 := rfl

theorem patternBytes_byte0 (p : Nat) : byteAt (patternBytes p) 0 = UInt8.ofNat p := rfl
theorem patternBytes_byte1 (p : Nat) : byteAt (patternBytes p) 1 = UInt8.ofNat (p / 256) := rfl

private theorem toNat_ofNat_mod (n : Nat) : (UInt8.ofNat n).toNat = n % 2 ^ 8 := by simp

/-- Stream bit `i` of the pattern reader is bit `i` of the pattern. -/
theorem patternReader_bit (p i : Nat) (hi : i < 16) :
    bitAt (patternReader p).bytes i = p.testBit i := by
  rw [bitAt_eq_testBit]
  by_cases h8 : i < 8
  · rw [show i / 8 = 0 by omega, show i % 8 = i by omega]
    show (byteAt (patternBytes p) 0).toNat.testBit i = _
    rw [patternBytes_byte0, toNat_ofNat_mod, Nat.testBit_mod_two_pow]
    simp [h8]
  · rw [show i / 8 = 1 by omega]
    show (byteAt (patternBytes p) 1).toNat.testBit (i % 8) = _
    rw [patternBytes_byte1, toNat_ofNat_mod, Nat.testBit_mod_two_pow,
      show (256 : Nat) = 2 ^ 8 from rfl, Nat.testBit_div_two_pow]
    simp only [Nat.mod_lt _ (show 8 > 0 by decide), decide_true, Bool.true_and]
    congr 1; omega

/-- `r` and `q` both have at least `n` bits left, and their next `n` bits
    are the same. -/
def Agree (r q : BitReader) (n : Nat) : Prop :=
  ∀ i < n, r.pos + i < r.size ∧ q.pos + i < q.size ∧
    bitAt r.bytes (r.pos + i) = bitAt q.bytes (q.pos + i)

/-- `readBit` inside the stream, in closed form. -/
theorem readBit_of_lt {r : BitReader} (h : r.pos < r.size) :
    readBit r = some (bitAt r.bytes r.pos, ⟨r.bytes, r.pos + 1⟩) := by
  simp [readBit, h]

/-- Locality: `decodeGo` reads its input one bit at a time and looks at
    nothing else, so a run that succeeds consuming `l` bits succeeds the
    same way on any reader with the same next `l` bits. -/
theorem decodeGo_local (c : Code) : ∀ (fuel len code first : Nat) (r q : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') →
    Agree r q (r'.pos - r.pos) →
    decodeGo c len code first q fuel = .ok (s, ⟨q.bytes, q.pos + (r'.pos - r.pos)⟩) := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r q s r' h hag
    have hpos := decodeGo_pos c (n + 1) len code first r s r' h
    obtain ⟨hr, hq, hbit⟩ := hag 0 (by dsimp only [BitPos] at *; omega)
    simp only [Nat.add_zero] at hr hq hbit
    unfold decodeGo at h ⊢
    rw [readBit_of_lt hr] at h
    rw [readBit_of_lt hq, ← hbit]
    generalize bitAt r.bytes r.pos = b at h ⊢
    have hag' : Agree ⟨r.bytes, r.pos + 1⟩ ⟨q.bytes, q.pos + 1⟩ (r'.pos - (r.pos + 1)) := by
      intro i hi
      obtain ⟨a, b, e⟩ := hag (i + 1) (by dsimp only [BitPos] at *; omega)
      dsimp only [BitPos] at *
      refine ⟨show r.pos + 1 + i < r.size by dsimp only [BitPos] at *; omega, show q.pos + 1 + i < q.size by dsimp only [BitPos] at *; omega, ?_⟩
      rw [show r.pos + 1 + i = r.pos + (i + 1) by dsimp only [BitPos] at *; omega, show q.pos + 1 + i = q.pos + (i + 1) by dsimp only [BitPos] at *; omega]
      exact e
    cases b <;> {
      simp only [Bool.false_eq_true, ↓reduceIte] at h ⊢
      split at h
      · rename_i hcond
        rw [if_pos hcond]
        revert h
        split
        · intro h
          cases h
          dsimp only [BitPos] at *
          rw [show r.pos + 1 - r.pos = 1 by dsimp only [BitPos] at *; omega]
        · intro h; contradiction
      · rename_i hcond
        rw [if_neg hcond]
        have hpos' := decodeGo_pos c n (len + 1) _ _ _ s r' h
        rw [ih (len + 1) _ _ _ _ s r' h hag']
        dsimp only [BitPos] at *
        congr 3
        exact (fun (a b c : Nat) (h : b + 1 < c) =>
          (by omega : a + 1 + (c - (b + 1)) = a + (c - b))) q.pos r.pos r'.pos hpos'.1
    }

/-- Locality of the canonical decoder (ADR 0005). -/
theorem decodeSym_local {c : Code} {r q r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) (hag : Agree r q (r'.pos - r.pos)) :
    decodeSym c q = .ok (s, ⟨q.bytes, q.pos + (r'.pos - r.pos)⟩) :=
  decodeGo_local c maxCodeLen 1 0 0 r q s r' h hag

/-- The primary table has exactly `2 ^ tableBits = 512` entries. -/
theorem buildTable_size (c : Code) : (buildTable c).size = 2 ^ tableBits := by
  simp [buildTable]

/-- Looking up an in-range pattern returns its entry, as defined. -/
theorem buildTable_getD (c : Code) {p : Nat} (hp : p < 2 ^ tableBits) :
    (buildTable c).getD p none = tableEntry c p := by
  simp [buildTable, Array.getD, hp]

/-- **Table-driven decoding is the canonical decoding** (ADR 0005). On every
    reader, the fast path returns exactly what `decodeSym` returns: the same
    symbol and reader on success, the same error on failure. Every theorem
    about `decodeSym` therefore holds of `decodeSymFast` too. -/
theorem decodeSymFast_eq (c : Code) (r : BitReader) :
    decodeSymFast c (buildTable c) r = decodeSym c r := by
  unfold decodeSymFast
  split
  · rfl
  · rename_i p r₂ hp
    have hlt : p < 2 ^ tableBits := readBits_lt _ _ _ _ hp
    rw [buildTable_getD c hlt]
    unfold tableEntry
    rcases hdec : decodeSym c (patternReader p) with e | ⟨s, r''⟩
    · rfl
    · dsimp only
      by_cases hl : r''.pos ≤ tableBits
      · rw [if_pos hl]
        dsimp only
        have hag : Agree (patternReader p) r (r''.pos - (patternReader p).pos) := by
          intro i hi
          have hi9 : i < tableBits := by
            simp only [patternReader] at hi; dsimp only [BitPos] at *; omega
          obtain ⟨hsz, hbit⟩ := readBits_bit _ _ _ _ hp i hi9
          refine ⟨?_, hsz, ?_⟩
          · show 0 + i < 16
            simp only [tableBits] at hi9; omega
          · rw [hbit]
            show bitAt (patternReader p).bytes (0 + i) = _
            rw [Nat.zero_add, patternReader_bit p i (by simp only [tableBits] at hi9; omega)]
        rw [decodeSym_local hdec hag]
        rfl
      · rw [if_neg hl]

/-- The peek succeeds whenever `n` bits remain. With `readBits_eof` (fewer
    than `n` bits remain, so it fails), this pins the fast path's guard:
    it looks up the table exactly when `pos + tableBits ≤ size`. -/
theorem readBits_some : ∀ (n : Nat) (r : BitReader), r.pos + n ≤ r.size →
    ∃ v r', readBits r n = some (v, r') := by
  intro n
  induction n with
  | zero => intro r _; exact ⟨0, r, rfl⟩
  | succ n ih =>
    intro r h
    have hlt : r.pos < r.size := by dsimp only [BitPos] at *; omega
    obtain ⟨v, r', hv⟩ := ih ⟨r.bytes, r.pos + 1⟩
      (show r.pos + 1 + n ≤ r.size by dsimp only [BitPos] at *; omega)
    exact ⟨(if bitAt r.bytes r.pos then 1 else 0) + 2 * v, r',
      by simp [readBits, readBit_of_lt hlt, hv]⟩

/-- A hit consumes between 1 and `tableBits` bits and names a symbol of the
    code. This is what lets the Rust pack an entry into a `u16` with length 0
    reserved for "fall back". -/
theorem tableEntry_some {c : Code} {p s l : Nat} (h : tableEntry c p = some (s, l)) :
    0 < l ∧ l ≤ tableBits ∧ s < c.lengths.size := by
  unfold tableEntry at h
  split at h
  · rename_i s' r' hdec
    split at h
    · rename_i hl
      cases h
      have hp := decodeSym_pos hdec
      exact ⟨hp.1, hl, decodeSym_in_range hdec⟩
    · contradiction
  · contradiction

/-- Every 9-bit pattern resolves in the fixed literal/length table: its codes
    are 7 to 9 bits long and complete, so the fast path never falls back on a
    fixed block while 9 bits remain. Checked by kernel evaluation. -/
theorem fixedLitLen_table_total :
    ∀ p, p < 2 ^ tableBits → (tableEntry fixedLitLen p).isSome = true := by
  decide +kernel

/-- Likewise every pattern resolves in the fixed (5-bit) distance table. -/
theorem fixedDist_table_total :
    ∀ p, p < 2 ^ tableBits → (tableEntry fixedDist p).isSome = true := by
  decide +kernel

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



/-! ### M7a — Tokens and the matcher (spec §3.1–3.2)

  The matcher re-checks every finder candidate, so both headline theorems
  hold for every `find`. -/

theorem extract_push_getElem (x : Array UInt8) (i : Nat) (hi : i < x.size) :
    (x.extract 0 i).push x[i] = x.extract 0 (i + 1) := by
  apply Array.ext
  · simp
  · intro j h1 h2
    simp at h1 h2
    rw [Array.getElem_push]
    split
    · simp
    · simp; congr 1; simp at *; omega

theorem accept_spec {x : Array UInt8} {i len dist : Nat}
    (h : accept x i len dist = true) :
    3 ≤ len ∧ len ≤ 258 ∧ 1 ≤ dist ∧ dist ≤ 32768 ∧ dist ≤ i ∧ i + len ≤ x.size ∧
      ∀ k, k < len → x[i + k]! = x[i + k - dist]! := by
  simp only [accept, Bool.and_eq_true, decide_eq_true_eq, List.all_eq_true,
    List.mem_range, beq_iff_eq] at h
  obtain ⟨⟨⟨⟨⟨⟨h1, h2⟩, h3⟩, h4⟩, h5⟩, h6⟩, h7⟩ := h
  exact ⟨h1, h2, h3, h4, h5, h6, h7⟩

/-- A copy whose source bytes agree with `x` extends a prefix of `x`. -/
theorem copyGo_extract (x : Array UInt8) (dist : Nat) (hd : 1 ≤ dist) :
    ∀ (m i : Nat), dist ≤ i → i + m ≤ x.size →
      (∀ k, k < m → x[i + k]! = x[i + k - dist]!) →
      copyGo dist (x.extract 0 i) m = x.extract 0 (i + m) := by
  intro m
  induction m with
  | zero => intro i _ _ _; simp [copyGo]
  | succ n ih =>
    intro i hdi hm heq
    simp only [copyGo]
    have hsz : (x.extract 0 i).size = i := by simp; omega
    have hsrc : (x.extract 0 i)[(x.extract 0 i).size - dist]! = x[i] := by
      rw [hsz]
      have h0 := heq 0 (by omega)
      simp only [Nat.add_zero] at h0
      rw [getElem!_pos x i (by omega)] at h0
      rw [h0, getElem!_pos x (i - dist) (by omega), getElem!_pos _ (i - dist) (by omega)]
      simp
    rw [hsrc, extract_push_getElem x i (by omega)]
    rw [ih (i + 1) (by omega) (by omega) (fun k hk => by
      have := heq (k + 1) (by omega)
      rw [show i + (k + 1) = i + 1 + k by omega] at this
      exact this)]
    congr 1; omega


/-- The generalized invariant: from position `i`, the remaining tokens
    replayed after `x.extract 0 i` give back `x`, and each is valid. -/
theorem compressFrom_spec (find : Finder) (x : Array UInt8) (i : Nat) (hi : i ≤ x.size) :
    (compressFrom find x i).foldl expandStep (x.extract 0 i) = x ∧
      ValidFrom (x.extract 0 i) (compressFrom find x i) := by
  rw [compressFrom]
  split
  · rename_i hlt
    have hlit : (compressFrom find x (i + 1)).foldl expandStep (x.extract 0 (i + 1)) = x ∧
        ValidFrom (x.extract 0 (i + 1)) (compressFrom find x (i + 1)) :=
      compressFrom_spec find x (i + 1) (by omega)
    have hlit' :
        (Token.literal x[i] :: compressFrom find x (i + 1)).foldl expandStep (x.extract 0 i) = x ∧
        ValidFrom (x.extract 0 i) (Token.literal x[i] :: compressFrom find x (i + 1)) := by
      simp only [List.foldl_cons, ValidFrom, expandStep, Token.valid, true_and]
      rw [extract_push_getElem x i hlt]
      exact hlit
    split
    · rename_i len dist _
      split
      · rename_i hacc
        obtain ⟨h1, h2, h3, h4, h5, h6, h7⟩ := accept_spec hacc
        have hcopy := copyGo_extract x dist h3 len i h5 h6 h7
        have hrec := compressFrom_spec find x (i + len) h6
        simp only [List.foldl_cons, ValidFrom, expandStep, Token.valid]
        rw [hcopy]
        refine ⟨hrec.1, ⟨h1, h2, h3, h4, ?_⟩, hrec.2⟩
        simp; omega
      · exact hlit'
    · exact hlit'
  · rename_i hge
    have : i = x.size := by omega
    subst this
    simp [ValidFrom]
termination_by x.size - i
decreasing_by
  all_goals first
    | omega
    | (have := accept_len_pos hacc; omega)

theorem expand_compressTokens (find : Finder) (x : Array UInt8) :
    expand (compressTokens find x) = x := by
  have h := (compressFrom_spec find x 0 (Nat.zero_le _)).1
  simpa [expand, compressTokens] using h

theorem compressTokens_valid (find : Finder) (x : Array UInt8) :
    Valid (compressTokens find x) := by
  have h := (compressFrom_spec find x 0 (Nat.zero_le _)).2
  simpa [Valid, compressTokens] using h


theorem validFrom_iff (out : Array UInt8) (ts : List Token) :
    ValidFrom out ts ↔
      ∀ n (h : n < ts.length), ts[n].valid ((ts.take n).foldl expandStep out).size := by
  induction ts generalizing out with
  | nil => simp [ValidFrom]
  | cons t ts ih =>
    simp only [ValidFrom, ih]
    constructor
    · rintro ⟨h0, hs⟩ n hn
      cases n with
      | zero => simpa using h0
      | succ n => simpa using hs n (by simpa using hn)
    · intro h
      refine ⟨by simpa using h 0 (by simp), fun n hn => ?_⟩
      simpa using h (n + 1) (by simpa using hn)

/-- `Valid` is the prefix reading of spec §3.1: token `n` is valid against
    the size of `expand` of the first `n` tokens. -/
theorem valid_iff_prefix (ts : List Token) :
    Valid ts ↔ ∀ n (h : n < ts.length), ts[n].valid (expand (ts.take n)).size :=
  validFrom_iff #[] ts

/-! ### M7a — Bit writer read-back (spec §3.3)

  What `writeBits` / `writeCode` put at position `p` reads back at `p`,
  whatever is written afterwards (`rest`). The `Agree` forms feed
  `decodeSym_local`, so a symbol decoded from a pattern reader is decoded
  the same way from the emitted stream. -/

section BitWriterProps
open BitWriter

theorem natOfBits_testBit : ∀ (n : Nat) (f : Nat → Bool) (j : Nat),
    (natOfBits f n).testBit j = (decide (j < n) && f j) := by
  intro n
  induction n with
  | zero => intro f j; simp [natOfBits]
  | succ n ih =>
    intro f j
    simp only [natOfBits]
    cases j with
    | zero =>
      cases h : f 0 <;> simp [Nat.testBit_zero, Nat.add_mod]
    | succ j =>
      rw [Nat.testBit_succ, show ((if f 0 then 1 else 0) + 2 * natOfBits (fun j => f (j + 1)) n) / 2
        = natOfBits (fun j => f (j + 1)) n by split <;> omega, ih]
      simp

theorem natOfBits_lt : ∀ (n : Nat) (f : Nat → Bool), natOfBits f n < 2 ^ n := by
  intro n
  induction n with
  | zero => intro f; simp [natOfBits]
  | succ n ih =>
    intro f
    have := ih (fun j => f (j + 1))
    simp only [natOfBits, Nat.pow_succ]
    split <;> omega

theorem toBytes_size (w : BitWriter) : w.toBytes.size = (w.bits.size + 7) / 8 := by
  simp [toBytes, ByteArray.size]

theorem toBytes_bitAt (w : BitWriter) (i : Nat) (h : i < w.bits.size) :
    bitAt w.toBytes i = w.bits[i] := by
  rw [bitAt_eq_testBit]
  have hk : i / 8 < w.toBytes.size := by rw [toBytes_size]; omega
  rw [byteAt, dif_pos hk]
  simp only [toBytes, ByteArray.getElem_eq_getElem_data, Array.getElem_ofFn, byteOf]
  rw [UInt8.toNat_ofNat', Nat.mod_eq_of_lt (natOfBits_lt 8 _), natOfBits_testBit]
  simp [Nat.mod_lt i (by decide : 8 > 0), Nat.div_add_mod, h]

theorem bitAt_toBytes_append (a b : Array Bool) (i : Nat) (h : i < a.size) :
    bitAt (BitWriter.mk (a ++ b)).toBytes i = a[i] := by
  rw [toBytes_bitAt _ i (by simp; omega)]
  simp [Array.getElem_append_left h]

theorem readBits_of_bits : ∀ (n : Nat) (r : BitReader) (v : Nat), v < 2 ^ n →
    (∀ i < n, r.pos + i < r.size ∧ bitAt r.bytes (r.pos + i) = v.testBit i) →
    readBits r n = some (v, ⟨r.bytes, r.pos + n⟩) := by
  intro n
  induction n with
  | zero => intro r v hv _; simp at hv; subst hv; rfl
  | succ n ih =>
    intro r v hv hb
    obtain ⟨hlt, hb0⟩ := hb 0 (by omega)
    simp only [Nat.add_zero] at hlt hb0
    have hv2 : v / 2 < 2 ^ n := by rw [Nat.pow_succ] at hv; omega
    have hb2 : ∀ i < n, (⟨r.bytes, r.pos + 1⟩ : BitReader).pos + i < (⟨r.bytes, r.pos + 1⟩ : BitReader).size ∧
        bitAt (⟨r.bytes, r.pos + 1⟩ : BitReader).bytes ((⟨r.bytes, r.pos + 1⟩ : BitReader).pos + i)
          = (v / 2).testBit i := by
      intro i hi
      have hi' : i + 1 < n + 1 := by omega
      obtain ⟨a, e⟩ := hb (i + 1) hi'
      dsimp only [BitReader.size, BitPos] at *
      refine ⟨by omega, ?_⟩
      dsimp only
      rw [Nat.add_assoc, Nat.add_comm 1 i, e, Nat.testBit_succ]
    have hrest := ih ⟨r.bytes, r.pos + 1⟩ (v / 2) hv2 hb2
    simp only [readBits, readBit_of_lt hlt, hrest, hb0, Option.bind_eq_bind, Option.bind_some,
      Option.pure_def, Option.some.injEq, Prod.mk.injEq, BitReader.mk.injEq, true_and]
    refine ⟨?_, by dsimp only [BitPos]; omega⟩
    rw [Nat.testBit_zero]
    split <;> simp_all <;> omega

theorem lsbBits_size (v n : Nat) : (lsbBits v n).size = n := by simp [lsbBits]

theorem writeBits_bits (w : BitWriter) (v n : Nat) :
    (w.writeBits v n).bits = w.bits ++ lsbBits v n := rfl

theorem writeBits_size (w : BitWriter) (v n : Nat) :
    (w.writeBits v n).bits.size = w.bits.size + n := by
  simp [writeBits_bits, lsbBits_size]

theorem bitAt_written (w : BitWriter) (v n : Nat) (rest : BitWriter) (i : Nat) (hi : i < n) :
    bitAt (BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes (w.bits.size + i)
      = v.testBit i := by
  rw [bitAt_toBytes_append _ _ _ (by rw [writeBits_size]; omega)]
  simp [writeBits_bits, lsbBits, Array.getElem_append_right]

theorem written_bits (w : BitWriter) (v n : Nat) (rest : BitWriter) :
    ∀ i < n, w.bits.size + i < (BitReader.mk (BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes 0).size ∧
      bitAt (BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes (w.bits.size + i)
        = v.testBit i := by
  intro i hi
  refine ⟨?_, bitAt_written w v n rest i hi⟩
  simp only [BitReader.size, toBytes_size, Array.size_append, writeBits_size]
  omega

theorem readBits_written (w : BitWriter) (v n : Nat) (rest : BitWriter) (hv : v < 2 ^ n) :
    readBits ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes, w.bits.size⟩ n
      = some (v, ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes,
          w.bits.size + n⟩) :=
  readBits_of_bits n _ v hv (written_bits w v n rest)

theorem agree_written (w : BitWriter) (v n : Nat) (rest : BitWriter) (q : BitReader)
    (hq : ∀ i < n, q.pos + i < q.size ∧ bitAt q.bytes (q.pos + i) = v.testBit i) :
    Agree q ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes, w.bits.size⟩ n := by
  intro i hi
  obtain ⟨a, e⟩ := hq i hi
  obtain ⟨a', e'⟩ := written_bits w v n rest i hi
  exact ⟨a, a', by rw [e, e']⟩

theorem agree_patternReader_written (w : BitWriter) (v n : Nat) (rest : BitWriter)
    (hn : n ≤ 16) :
    Agree (patternReader v)
      ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes, w.bits.size⟩ n :=
  agree_written w v n rest _ fun i hi =>
    ⟨by rw [patternReader_size]; show 0 + i < 16; omega,
     by show bitAt (patternReader v).bytes (0 + i) = _; rw [Nat.zero_add]; exact patternReader_bit v i (by omega)⟩

theorem decodeSym_written {c : Code} {w : BitWriter} {v n : Nat} {s : Nat} {r' : BitReader}
    (rest : BitWriter) (h : decodeSym c (patternReader v) = .ok (s, r')) (hl : r'.pos = n)
    (hn : n ≤ 16) :
    decodeSym c ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes, w.bits.size⟩
      = .ok (s, ⟨(BitWriter.mk ((w.writeBits v n).bits ++ rest.bits)).toBytes,
          w.bits.size + n⟩) := by
  subst hl
  have hag := agree_patternReader_written w v (r'.pos - (patternReader v).pos) rest
    (by show r'.pos - 0 ≤ 16; omega)
  have hd := decodeSym_local h hag
  rw [show r'.pos - (patternReader v).pos = r'.pos from Nat.sub_zero _] at hd
  exact hd

theorem reverseBits_lt (code len : Nat) : reverseBits code len < 2 ^ len := natOfBits_lt _ _

theorem reverseBits_testBit (code len i : Nat) (hi : i < len) :
    (reverseBits code len).testBit i = code.testBit (len - 1 - i) := by
  simp [reverseBits, natOfBits_testBit, hi]

theorem writeCode_eq (w : BitWriter) (code len : Nat) :
    w.writeCode code len = w.writeBits (reverseBits code len) len := rfl

theorem bitAt_writeCode (w : BitWriter) (code len : Nat) (rest : BitWriter) (i : Nat) (hi : i < len) :
    bitAt (BitWriter.mk ((w.writeCode code len).bits ++ rest.bits)).toBytes (w.bits.size + i)
      = code.testBit (len - 1 - i) := by
  rw [writeCode_eq, bitAt_written _ _ _ _ _ hi, reverseBits_testBit _ _ _ hi]

theorem decodeSym_writeCode {c : Code} {w : BitWriter} {code len s : Nat} {r' : BitReader}
    (rest : BitWriter) (h : decodeSym c (patternReader (reverseBits code len)) = .ok (s, r'))
    (hl : r'.pos = len) (hn : len ≤ 16) :
    decodeSym c ⟨(BitWriter.mk ((w.writeCode code len).bits ++ rest.bits)).toBytes, w.bits.size⟩
      = .ok (s, ⟨(BitWriter.mk ((w.writeCode code len).bits ++ rest.bits)).toBytes,
          w.bits.size + len⟩) :=
  decodeSym_written rest h hl hn

/-- BFINAL=1, BTYPE=01, then literal 0's fixed code `0x30` (8 bits,
    MSB first) packs to `0x63 0x00`, as in a zlib fixed-Huffman stream. -/
example : (BitWriter.empty.writeBits 1 1 |>.writeBits 1 2 |>.writeCode 0x30 8).toBytes.data = #[99, 0] := by decide +kernel

end BitWriterProps

/-! ### P10, P11 — Encoder validity and round trip -/

/-- A byte of a stream laid out as `pre ++ mid ++ post`, read at offset `i`
    into `mid`. -/
theorem byteAt_mid {bs : ByteArray} {pre mid post : Array UInt8}
    (h : bs.data = pre ++ mid ++ post) (i : Nat) (hi : i < mid.size) :
    byteAt bs (pre.size + i) = mid[i] := by
  have hs : pre.size + i < bs.size := by
    simp only [ByteArray.size, h, Array.size_append]; omega
  unfold byteAt; rw [dif_pos hs]
  simp only [ByteArray.getElem_eq_getElem_data]
  have : bs.data[pre.size + i] = (pre ++ mid ++ post)[pre.size + i]'(by rw [← h]; exact hs) := by
    simp only [h]
  rw [this, Array.getElem_append_left (by simp; omega), Array.getElem_append_right (by omega)]
  simp

/-- Sixteen bits read from a byte boundary are the two bytes there,
    little-endian: how LEN and NLEN are read (RFC 1951 §3.2.4). -/
theorem readBits16_aligned (bs : ByteArray) (p : Nat) (hp : p + 1 < bs.size) :
    readBits ⟨bs, 8 * p⟩ 16 =
      some ((byteAt bs p).toNat + 256 * (byteAt bs (p + 1)).toNat, ⟨bs, 8 * p + 16⟩) := by
  have h0 := (byteAt bs p).toNat_lt
  have h1 := (byteAt bs (p + 1)).toNat_lt
  have hv : (byteAt bs p).toNat + 256 * (byteAt bs (p + 1)).toNat
      = 2 ^ 8 * (byteAt bs (p + 1)).toNat + (byteAt bs p).toNat := by omega
  rw [hv]
  apply readBits_of_bits
  · omega
  · intro i hi
    refine ⟨show 8 * p + i < bs.size * 8 by omega, ?_⟩
    rw [bitAt_eq_testBit, Nat.testBit_two_pow_mul_add _ (by omega)]
    by_cases h8 : i < 8
    · rw [if_pos h8, show (8 * p + i) / 8 = p by omega, show (8 * p + i) % 8 = i by omega]
    · rw [if_neg h8, show (8 * p + i) / 8 = p + 1 by omega, show (8 * p + i) % 8 = i - 8 by omega]

/-- A header byte of 0 or 1 (`encodeBlock`'s) reads as a stored block with
    that BFINAL. -/
theorem readHeader_storedByte (bs : ByteArray) (p : Nat) (f : Bool) (hp : p < bs.size)
    (hb : byteAt bs p = (if f then 1 else 0)) :
    readHeader ⟨bs, 8 * p⟩ = .ok (⟨f, .stored⟩, ⟨bs, 8 * p + 3⟩) := by
  have h2 : readBits ⟨bs, 8 * p + 1⟩ 2 = some (0, ⟨bs, 8 * p + 1 + 2⟩) := by
    apply readBits_of_bits 2 _ 0 (by decide)
    intro i hi
    refine ⟨show 8 * p + 1 + i < bs.size * 8 by omega, ?_⟩
    rw [bitAt_eq_testBit, show (8 * p + 1 + i) / 8 = p by omega,
      show (8 * p + 1 + i) % 8 = i + 1 by omega, hb]
    have : i = 0 ∨ i = 1 := by omega
    rcases this with rfl | rfl <;> cases f <;> decide
  have h0 : bitAt bs (8 * p) = f := by
    rw [bitAt_eq_testBit, show 8 * p / 8 = p by omega, show 8 * p % 8 = 0 by omega, hb]
    cases f <;> decide
  have h1 := readBit_of_lt (r := ⟨bs, 8 * p⟩) (show 8 * p < bs.size * 8 by omega)
  unfold readHeader
  rw [h1]
  dsimp only
  rw [h0, h2]
  simp

/-- One `encodeBlock` anywhere in a stream reads back exactly: header, then
    the payload, leaving the reader at the next byte after the block. -/
theorem storedBlock_reads {bs : ByteArray} {pre post payload : Array UInt8} {f : Bool}
    (hn : payload.size ≤ maxStored) (h : bs.data = pre ++ encodeBlock f payload ++ post)
    (out : Array UInt8) :
    readHeader ⟨bs, 8 * pre.size⟩ = .ok (⟨f, .stored⟩, ⟨bs, 8 * pre.size + 3⟩) ∧
    readStored ⟨bs, 8 * pre.size + 3⟩ out =
      .ok (out ++ payload, ⟨bs, 8 * (pre.size + 5 + payload.size)⟩) := by
  unfold maxStored at hn
  have hsz : (encodeBlock f payload).size = 5 + payload.size := by
    simp [encodeBlock]
  have hbs : bs.size = pre.size + (5 + payload.size) + post.size := by
    simp only [ByteArray.size, h, Array.size_append, hsz]
  have hB := byteAt_mid h
  have b0 := hB 0 (by omega)
  have b1 := hB 1 (by omega)
  have b2 := hB 2 (by omega)
  have b3 := hB 3 (by omega)
  have b4 := hB 4 (by omega)
  simp only [encodeBlock] at b0 b1 b2 b3 b4
  simp at b0 b1 b2 b3 b4
  refine ⟨readHeader_storedByte bs pre.size f (by omega) b0, ?_⟩
  have hpay : ∀ k (hk : k < payload.size), byteAt bs (pre.size + 5 + k) = payload[k] := by
    intro k hk
    rw [show pre.size + 5 + k = pre.size + (5 + k) by omega, hB (5 + k) (by omega)]
    simp only [encodeBlock]
    rw [Array.getElem_append_right (by simp)]
    simp
  have hal : alignToByte ⟨bs, 8 * pre.size + 3⟩ = ⟨bs, 8 * (pre.size + 1)⟩ := by
    show (⟨bs, (8 * pre.size + 3 + 7) / 8 * 8⟩ : BitReader) = _
    congr 1; dsimp only [BitPos]; omega
  have hlen := readBits16_aligned bs (pre.size + 1) (by omega)
  rw [show pre.size + 1 + 1 = pre.size + 2 by omega, b1, b2] at hlen
  have hnlen := readBits16_aligned bs (pre.size + 3) (by omega)
  rw [show pre.size + 3 + 1 = pre.size + 4 by omega, b3, b4] at hnlen
  simp only [UInt8.toNat_ofNat'] at hlen hnlen
  rw [show payload.size % 256 % 2 ^ 8 + 256 * (payload.size / 256 % 2 ^ 8) = payload.size by omega,
    show 8 * (pre.size + 1) + 16 = 8 * (pre.size + 3) by omega] at hlen
  rw [show (65535 - payload.size) % 256 % 2 ^ 8 + 256 * ((65535 - payload.size) / 256 % 2 ^ 8)
      = 65535 - payload.size by omega] at hnlen
  unfold readStored
  rw [hal]
  dsimp only
  rw [hlen]
  dsimp only
  rw [hnlen]
  dsimp only
  rw [if_neg (by omega)]
  simp only [BitReader.size]
  rw [if_neg (show ¬ (bs.size * 8 < 8 * (pre.size + 3) + 16 + 8 * payload.size) by omega)]
  have hl : (List.map (fun k => byteAt bs ((8 * (pre.size + 3) + 16) / 8 + k))
      (List.range payload.size)).toArray = payload := by
    apply Array.ext
    · simp
    · intro k h1 h2
      simp only [List.getElem_toArray, List.getElem_map, List.getElem_range]
      rw [show (8 * (pre.size + 3) + 16) / 8 = pre.size + 5 by omega]
      exact hpay k h2
  rw [hl, show 8 * (pre.size + 3) + 16 + 8 * payload.size = 8 * (pre.size + 5 + payload.size) by omega]

/-- `encodeStored.go` only appends to its accumulator. -/
theorem encodeStored_go_prefix : ∀ (rest acc : Array UInt8),
    ∃ t, encodeStored.go rest acc = acc ++ t := by
  intro rest acc
  induction rest, acc using encodeStored.go.induct with
  | case1 rest acc h =>
    exact ⟨_, by rw [encodeStored.go, if_pos h]⟩
  | case2 rest acc h ih =>
    obtain ⟨t, ht⟩ := ih
    exact ⟨_, by rw [encodeStored.go, if_neg h, ht, Array.append_assoc]⟩

/-- The single-block branch of `encodeStored` is `go`'s base case. -/
theorem encodeStored_eq_go (x : ByteArray) : encodeStored x = ⟨encodeStored.go x.data #[]⟩ := by
  unfold encodeStored
  split
  · rename_i h
    rw [encodeStored.go, if_pos (show x.data.size ≤ maxStored from h), Array.empty_append]
  · rfl

/-- The induction behind `decode_encodeStored`, over `go`'s chunks: started
    at the end of the bytes already emitted (`acc`), the loop decodes the
    rest. Every block is at least 5 bytes, so one unit of fuel per byte
    still to read is enough. -/
theorem decodeFuelLoop_go (bs : ByteArray) (limit : Nat) : ∀ (rest acc : Array UInt8),
    bs.data = encodeStored.go rest acc → ∀ (out : Array UInt8) (fuel : Nat),
    out.size + rest.size ≤ limit → bs.size - acc.size < fuel →
    decodeFuelLoop bs limit ⟨bs, 8 * acc.size⟩ out fuel = .ok ⟨out ++ rest⟩ := by
  intro rest acc
  induction rest, acc using encodeStored.go.induct with
  | case1 rest acc h =>
    intro hbs out fuel hlim hfuel
    rw [encodeStored.go, if_pos h] at hbs
    have hbs' : bs.data = acc ++ encodeBlock true rest ++ #[] := by rw [hbs, Array.append_empty]
    obtain ⟨hh, hs⟩ := storedBlock_reads h hbs' out
    obtain ⟨fuel, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by omega⟩
    rw [decodeFuelLoop.eq_2, hh]
    simp only [bind, Except.bind, decodeBlockBody]
    rw [hs]
    dsimp only
    simp only [Array.size_append]
    rw [if_neg (by omega), if_pos trivial]
  | case2 rest acc h ih =>
    intro hbs out fuel hlim hfuel
    rw [encodeStored.go, if_neg h] at hbs
    obtain ⟨t, ht⟩ := encodeStored_go_prefix (rest.extract maxStored)
      (acc ++ encodeBlock false (rest.extract 0 maxStored))
    have hc : (rest.extract 0 maxStored).size = maxStored := by
      simp [Array.size_extract]; omega
    obtain ⟨hh, hs⟩ := storedBlock_reads (by omega) (ht ▸ hbs) out
    have hsz : (encodeBlock false (rest.extract 0 maxStored)).size = 5 + maxStored := by
      simp [encodeBlock, hc]
    obtain ⟨fuel, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by omega⟩
    rw [decodeFuelLoop.eq_2, hh]
    simp only [bind, Except.bind, decodeBlockBody]
    rw [hs]
    have hrest : rest.extract 0 maxStored ++ rest.extract maxStored = rest := by
      rw [Array.extract_append_extract]; simp; omega
    have hlim' : (out ++ rest.extract 0 maxStored).size ≤ limit := by
      simp only [Array.size_append]; rw [hc]; unfold maxStored at *; omega
    dsimp only
    rw [if_neg (by omega)]
    simp only [Bool.false_eq_true, if_false]
    have hbsz : bs.size = acc.size + (5 + maxStored) + t.size := by
      simp only [ByteArray.size, hbs, ht, Array.size_append, hsz]
    have := ih hbs (out ++ rest.extract 0 maxStored) fuel
      (by simp only [Array.size_append, Array.size_extract] at hlim' ⊢; omega)
      (by simp only [Array.size_append, hsz]; omega)
    simp only [Array.size_append, hsz] at this
    rw [hc, show acc.size + 5 + maxStored = acc.size + (5 + maxStored) by omega, this,
      Array.append_assoc, hrest]

/-- P11: the stored encoder round-trips every input, at any limit that
    admits it. This covers multi-block inputs (over 65535 bytes); Rust's
    `deflate_stored` is the counterpart, tested by the differential harness. -/
theorem decode_encodeStored (x : ByteArray) (limit : Nat) (h : x.size ≤ limit) :
    decode (encodeStored x) limit = .ok x := by
  rw [encodeStored_eq_go]
  have := decodeFuelLoop_go ⟨encodeStored.go x.data #[]⟩ limit x.data #[] rfl #[]
    (8 * (⟨encodeStored.go x.data #[]⟩ : ByteArray).size + 1)
    (by rw [Array.size_empty, Nat.zero_add]; exact h) (by omega)
  unfold decode decodeFuel
  change decodeFuelLoop _ limit ⟨_, 8 * (#[] : Array UInt8).size⟩ #[] _ = _
  rw [this, Array.empty_append]

/-- Empty input produces a valid stream: one final stored block with LEN = 0
    that the model's own decoder decodes back to the empty array. -/
theorem encodeStored_empty (limit : Nat) : decode (encodeStored ⟨#[]⟩) limit = .ok ⟨#[]⟩ :=
  decode_encodeStored _ limit (Nat.zero_le _)

/-- P10, stated on its own: encoding is a stream the decoder accepts. -/
theorem encodeStored_valid : (decode (encodeStored ⟨#[]⟩) 0).isOk = true := by
  rw [encodeStored_empty 0]; rfl

/-! ### M7a — Fixed-Huffman emitter round trip (spec §3.4)

  Each code the emitter writes is checked once on a pattern reader by
  kernel evaluation (`litCheck_all`, `distCheck_all`) and lifted to any
  stream by `decodeSym_writeCode`. Length and distance slots are argued
  structurally (`slot_spec`): consecutive bases are at most `2 ^ extra`
  apart, so the extra value always fits. Rust counterpart: `encode_fixed.rs`. -/

section EmitFixedProps
open BitWriter

def litCheck (s : Nat) : Bool :=
  match decodeSym fixedLitLen (patternReader (reverseBits (fixedLitCode s).1 (fixedLitCode s).2)) with
  | .ok (s', r') => s' == s && r'.pos == (fixedLitCode s).2
  | .error _ => false

/-- Every fixed literal/length code decodes, on a pattern reader, to its own
    symbol after exactly its own length. Kernel evaluation, 288 cases. -/
theorem litCheck_all : ∀ s, s < 288 → litCheck s = true := by decide +kernel
theorem litCheck_ok (s : Nat) (h : litCheck s = true) :
    ∃ r', decodeSym fixedLitLen (patternReader (reverseBits (fixedLitCode s).1 (fixedLitCode s).2))
      = .ok (s, r') ∧ r'.pos = (fixedLitCode s).2 := by
  unfold litCheck at h
  revert h
  cases decodeSym fixedLitLen (patternReader (reverseBits (fixedLitCode s).1 (fixedLitCode s).2)) with
  | error e => intro h; contradiction
  | ok p => 
    obtain ⟨s', r'⟩ := p
    intro h
    simp only [Bool.and_eq_true, beq_iff_eq] at h
    obtain ⟨rfl, hl⟩ := h
    exact ⟨r', rfl, hl⟩

theorem writeLit_size (w : BitWriter) (s : Nat) :
    (writeLit w s).bits.size = w.bits.size + (fixedLitCode s).2 := by
  simp [writeLit, writeCode_eq, writeBits_size]
theorem fixedLitCode_len (s : Nat) : 7 ≤ (fixedLitCode s).2 ∧ (fixedLitCode s).2 ≤ 9 := by
  by_cases a : s < 144 <;> by_cases b : s < 256 <;> by_cases c : s < 280 <;>
    simp [fixedLitCode, a, b, c]

/-- **Symbol codes.** Wherever `writeLit w s` sits in a stream, `decodeSym
    fixedLitLen` there returns `s` and stops right after the code. -/
theorem fixedLit_code_decodes {bs : ByteArray} {w : BitWriter} {R : Array Bool} {s : Nat}
    (hs : s < 288) (hB : bs = (BitWriter.mk ((writeLit w s).bits ++ R)).toBytes) :
    decodeSym fixedLitLen ⟨bs, w.bits.size⟩ = .ok (s, ⟨bs, (writeLit w s).bits.size⟩) := by
  obtain ⟨r', hd, hl⟩ := litCheck_ok s (litCheck_all s hs)
  subst hB
  rw [writeLit_size]
  exact decodeSym_writeCode (w := w) ⟨R⟩ hd hl (by have := fixedLitCode_len s; omega)

def distCheck (s : Nat) : Bool :=
  match decodeSym fixedDist (patternReader (reverseBits s 5)) with
  | .ok (s', r') => s' == s && r'.pos == 5
  | .error _ => false

/-- Likewise every 5-bit distance code 0..29. -/
theorem distCheck_all : ∀ s, s < 30 → distCheck s = true := by decide +kernel

/-- The same for the fixed distance code: code = symbol, 5 bits. -/
theorem fixedDist_code_decodes {bs : ByteArray} {w : BitWriter} {R : Array Bool} {s : Nat}
    (hs : s < 30) (hB : bs = (BitWriter.mk ((w.writeCode s 5).bits ++ R)).toBytes) :
    decodeSym fixedDist ⟨bs, w.bits.size⟩ = .ok (s, ⟨bs, (w.writeCode s 5).bits.size⟩) := by
  have hc := distCheck_all s hs
  unfold distCheck at hc
  split at hc
  · rename_i s' r' hd
    simp only [Bool.and_eq_true, beq_iff_eq] at hc
    obtain ⟨rfl, hl⟩ := hc
    subst hB
    rw [writeCode_eq, writeBits_size]
    exact decodeSym_writeCode (w := w) ⟨R⟩ hd hl (by omega)
  · contradiction

theorem slotGo_spec (base : Array Nat) (v : Nat) (h0 : base[0]! ≤ v) :
    ∀ k, 0 < k → slotGo base v k < k ∧ base[slotGo base v k]! ≤ v ∧
      ∀ j, slotGo base v k < j → j < k → v < base[j]! := by
  intro k hk
  induction k with
  | zero => omega
  | succ k ih =>
    simp only [slotGo]
    split
    · rename_i h; exact ⟨by omega, h, fun j h1 h2 => by omega⟩
    · rename_i h
      cases k with
      | zero => exact absurd h0 h
      | succ k =>
        obtain ⟨a, b, c⟩ := ih (by omega)
        refine ⟨by omega, b, fun j h1 h2 => ?_⟩
        by_cases hj : j = k + 1
        · subst hj; omega
        · exact c j h1 (by omega)

/-- The slot search: `slot` picks a base at or below `v`, and when
    consecutive bases are at most `2 ^ extra` apart, `v - base` fits in the
    slot's extra bits. A table argument, so no 32768-case evaluation. -/
theorem slot_spec (base extra : Array Nat) (v : Nat) (hsz : 0 < base.size) (h0 : base[0]! ≤ v)
    (hstep : ∀ i, i + 1 < base.size → base[i + 1]! ≤ base[i]! + 2 ^ extra[i]!)
    (hlast : v < base[base.size - 1]! + 2 ^ extra[base.size - 1]!) :
    slot base v < base.size ∧ base[slot base v]! ≤ v ∧
      v - base[slot base v]! < 2 ^ extra[slot base v]! := by
  obtain ⟨a, b, c⟩ := slotGo_spec base v h0 base.size hsz
  unfold slot
  refine ⟨a, b, ?_⟩
  by_cases hi : slotGo base v base.size + 1 < base.size
  · have := c _ (by omega) hi
    have := hstep _ hi
    omega
  · have : slotGo base v base.size = base.size - 1 := by omega
    rw [this] at b ⊢; omega

theorem lengthBase_step' : ∀ i, i < 28 →
    lengthBase[i + 1]! ≤ lengthBase[i]! + 2 ^ lengthExtra[i]! := by decide +kernel
theorem lengthBase_step (i : Nat) (h : i + 1 < lengthBase.size) :
    lengthBase[i + 1]! ≤ lengthBase[i]! + 2 ^ lengthExtra[i]! :=
  lengthBase_step' i (by have : lengthBase.size = 29 := rfl; omega)
theorem distBase_step' : ∀ i, i < 29 →
    distBase[i + 1]! ≤ distBase[i]! + 2 ^ distExtra[i]! := by decide +kernel
theorem distBase_step (i : Nat) (h : i + 1 < distBase.size) :
    distBase[i + 1]! ≤ distBase[i]! + 2 ^ distExtra[i]! :=
  distBase_step' i (by have : distBase.size = 30 := rfl; omega)

/-- What `lengthSym` returns, for an in-range length. -/
theorem lengthSym_spec (len : Nat) (h1 : 3 ≤ len) (h2 : len ≤ 258) :
    257 ≤ (lengthSym len).1 ∧ (lengthSym len).1 ≤ 285 ∧
      lengthExtra[(lengthSym len).1 - 257]! = (lengthSym len).2.2 ∧
      (lengthSym len).2.1 < 2 ^ (lengthSym len).2.2 ∧
      lengthBase[(lengthSym len).1 - 257]! + (lengthSym len).2.1 = len := by
  obtain ⟨a, b, c⟩ := slot_spec lengthBase lengthExtra len (by decide) (by simp [lengthBase]; omega)
    lengthBase_step (by simp [lengthBase, lengthExtra]; omega)
  dsimp only [lengthSym]
  rw [Nat.add_sub_cancel_left]
  have : lengthBase.size = 29 := rfl
  exact ⟨by omega, by omega, rfl, c, by omega⟩

theorem distSym_spec (dist : Nat) (h1 : 1 ≤ dist) (h2 : dist ≤ 32768) :
    (distSym dist).1 ≤ 29 ∧ distExtra[(distSym dist).1]! = (distSym dist).2.2 ∧
      (distSym dist).2.1 < 2 ^ (distSym dist).2.2 ∧
      distBase[(distSym dist).1]! + (distSym dist).2.1 = dist := by
  obtain ⟨a, b, c⟩ := slot_spec distBase distExtra dist (by decide) (by simp [distBase]; omega)
    distBase_step (by simp [distBase, distExtra]; omega)
  dsimp only [distSym]
  have : distBase.size = 30 := rfl
  exact ⟨by omega, rfl, c, by omega⟩

/-- **Length codes.** For every length 3..258, `readLength` on the chosen
    symbol and the written extra bits returns the length. -/
theorem lengthSym_reads {bs : ByteArray} {w : BitWriter} {R : Array Bool} (len : Nat)
    (h1 : 3 ≤ len) (h2 : len ≤ 258)
    (hB : bs = (BitWriter.mk ((w.writeBits (lengthSym len).2.1 (lengthSym len).2.2).bits ++ R)).toBytes) :
    readLength (lengthSym len).1 ⟨bs, w.bits.size⟩ =
      .ok (len, ⟨bs, (w.writeBits (lengthSym len).2.1 (lengthSym len).2.2).bits.size⟩) := by
  obtain ⟨a, b, c, d, e⟩ := lengthSym_spec len h1 h2
  subst hB
  unfold readLength
  rw [if_pos ⟨a, b⟩]
  dsimp only
  rw [c, readBits_written w _ _ ⟨R⟩ d]
  simp only [e, writeBits_size]

/-- **Distance codes.** For every distance 1..32768, `readDistance` on the
    chosen symbol and the written extra bits returns the distance. -/
theorem distSym_reads {bs : ByteArray} {w : BitWriter} {R : Array Bool} (dist : Nat)
    (h1 : 1 ≤ dist) (h2 : dist ≤ 32768)
    (hB : bs = (BitWriter.mk ((w.writeBits (distSym dist).2.1 (distSym dist).2.2).bits ++ R)).toBytes) :
    readDistance (distSym dist).1 ⟨bs, w.bits.size⟩ =
      .ok (dist, ⟨bs, (w.writeBits (distSym dist).2.1 (distSym dist).2.2).bits.size⟩) := by
  obtain ⟨a, c, d, e⟩ := distSym_spec dist h1 h2
  subst hB
  unfold readDistance
  rw [if_pos a]
  rw [c, readBits_written w _ _ ⟨R⟩ d]
  simp only [e, writeBits_size]


theorem writeLit_bits (w : BitWriter) (s : Nat) :
    (writeLit w s).bits = w.bits ++ lsbBits (reverseBits (fixedLitCode s).1 (fixedLitCode s).2)
      (fixedLitCode s).2 := rfl

theorem foldl_expandStep_size : ∀ (ts : List Token) (out : Array UInt8),
    out.size ≤ (ts.foldl expandStep out).size := by
  intro ts
  induction ts with
  | nil => intro out; simp
  | cons t ts ih =>
    intro out
    have h1 := ih (expandStep out t)
    have h2 : out.size ≤ (expandStep out t).size := by
      cases t <;> simp [expandStep, copyGo_size]
    simp only [List.foldl_cons]; omega

theorem emitToken_bits (w : BitWriter) (t : Token) :
    ∃ T, (emitToken w t).bits = w.bits ++ T ∧ 1 ≤ T.size := by
  cases t with
  | literal b =>
    refine ⟨_, writeLit_bits w b.toNat, ?_⟩
    simp only [lsbBits_size]; have := fixedLitCode_len b.toNat; omega
  | «match» len dist =>
    refine ⟨lsbBits (reverseBits (fixedLitCode (lengthSym len).1).1 (fixedLitCode (lengthSym len).1).2)
        (fixedLitCode (lengthSym len).1).2 ++ lsbBits (lengthSym len).2.1 (lengthSym len).2.2 ++
        lsbBits (reverseBits (distSym dist).1 5) 5 ++ lsbBits (distSym dist).2.1 (distSym dist).2.2,
      ?_, ?_⟩
    · simp only [emitToken, writeBits_bits, writeCode_eq, writeLit_bits, Array.append_assoc]
    · simp only [Array.size_append, lsbBits_size]; have := fixedLitCode_len (lengthSym len).1; omega

theorem foldl_emitToken_bits : ∀ (ts : List Token) (w : BitWriter),
    ∃ T, (ts.foldl emitToken w).bits = w.bits ++ T ∧ ts.length ≤ T.size := by
  intro ts
  induction ts with
  | nil => intro w; exact ⟨#[], by simp, by simp⟩
  | cons t ts ih =>
    intro w
    obtain ⟨T1, h1, s1⟩ := emitToken_bits w t
    obtain ⟨T2, h2, s2⟩ := ih (emitToken w t)
    refine ⟨T1 ++ T2, ?_, ?_⟩
    · simp only [List.foldl_cons, h2, h1, Array.append_assoc]
    · simp only [List.length_cons, Array.size_append]; omega

/-- The end-of-block code: symbol 256 is 7 zero bits. -/
def endBits : Array Bool :=
  lsbBits (reverseBits (fixedLitCode 256).1 (fixedLitCode 256).2) (fixedLitCode 256).2

/-- The block-body invariant: the reader sits at the bit offset of the next
    token, the output is the expansion so far, and fuel exceeds the tokens
    left (one iteration per token, plus one for symbol 256). -/
theorem emitFixed_loop (bs : ByteArray) (limit : Nat) : ∀ (ts : List Token) (w : BitWriter)
    (out : Array UInt8) (fuel : Nat),
    bs = (BitWriter.mk ((ts.foldl emitToken w).bits ++ endBits)).toBytes →
    ValidFrom out ts → (ts.foldl expandStep out).size ≤ limit → ts.length < fuel →
    decodeHuffBlock fixedLitLen fixedDist ⟨bs, w.bits.size⟩ out limit fuel
      = .ok (ts.foldl expandStep out, ⟨bs, (ts.foldl emitToken w).bits.size + 7⟩) := by
  intro ts
  induction ts with
  | nil =>
    intro w out fuel hbs _ _ hf
    obtain ⟨k, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by simp at hf; omega⟩
    have hd := fixedLit_code_decodes (bs := bs) (w := w) (R := #[]) (s := 256) (by decide)
      (by rw [hbs]; simp [endBits, writeLit_bits])
    simp only [decodeHuffBlock, hd, bind, Except.bind]
    rw [if_neg (by decide), if_pos trivial]
    simp [writeLit_size, fixedLitCode]
  | cons t ts ih =>
    intro w out fuel hbs hv hlim hf
    obtain ⟨k, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by simp at hf; omega⟩
    obtain ⟨T, hT, _⟩ := foldl_emitToken_bits ts (emitToken w t)
    have hbs' : bs = (BitWriter.mk ((emitToken w t).bits ++ (T ++ endBits))).toBytes := by
      rw [hbs, List.foldl_cons, hT, Array.append_assoc]
    obtain ⟨hvt, hvs⟩ := hv
    simp only [List.foldl_cons] at hlim ⊢
    have hgrow := foldl_expandStep_size ts (expandStep out t)
    have ih' := ih (emitToken w t) (expandStep out t) k (by rw [hbs, List.foldl_cons]) hvs hlim
      (by simp at hf; omega)
    cases t with
    | literal b =>
      have hd := fixedLit_code_decodes (bs := bs) (w := w) (R := T ++ endBits) (s := b.toNat)
        (by have := b.toNat_lt; omega) hbs'
      simp only [decodeHuffBlock, hd, bind, Except.bind]
      simp only [expandStep, Array.size_push] at hgrow hlim
      rw [if_pos b.toNat_lt, if_neg (by omega), UInt8.ofNat_toNat]
      exact ih'
    | «match» len dist =>
      obtain ⟨h1, h2, h3, h4, h5⟩ := hvt
      have hls := lengthSym_spec len h1 h2
      have hds := distSym_spec dist h3 h4
      have hd1 := fixedLit_code_decodes (bs := bs) (w := w)
        (R := lsbBits (lengthSym len).2.1 (lengthSym len).2.2 ++
          lsbBits (reverseBits (distSym dist).1 5) 5 ++
          lsbBits (distSym dist).2.1 (distSym dist).2.2 ++ (T ++ endBits))
        (s := (lengthSym len).1) (by omega)
        (by rw [hbs']; simp only [emitToken, writeBits_bits, writeCode_eq, writeLit_bits,
              Array.append_assoc])
      have hd2 := lengthSym_reads (bs := bs) (w := writeLit w (lengthSym len).1)
        (R := lsbBits (reverseBits (distSym dist).1 5) 5 ++
          lsbBits (distSym dist).2.1 (distSym dist).2.2 ++ (T ++ endBits)) len h1 h2
        (by rw [hbs']; simp only [emitToken, writeBits_bits, writeCode_eq, Array.append_assoc])
      have hd3 := fixedDist_code_decodes (bs := bs)
        (w := (writeLit w (lengthSym len).1).writeBits (lengthSym len).2.1 (lengthSym len).2.2)
        (R := lsbBits (distSym dist).2.1 (distSym dist).2.2 ++ (T ++ endBits))
        (s := (distSym dist).1) (by omega)
        (by rw [hbs']; simp only [emitToken, writeBits_bits, writeCode_eq, Array.append_assoc])
      have hd4 := distSym_reads (bs := bs)
        (w := ((writeLit w (lengthSym len).1).writeBits (lengthSym len).2.1
          (lengthSym len).2.2).writeCode (distSym dist).1 5)
        (R := T ++ endBits) dist h3 h4
        (by rw [hbs']; simp only [emitToken, writeBits_bits, Array.append_assoc])
      simp only [expandStep, copyGo_size] at hgrow hlim
      simp only [decodeHuffBlock, hd1, hd2, hd3, hd4, bind, Except.bind]
      rw [if_neg (by omega), if_neg (by omega), if_neg (by omega)]
      have hcb : copyBack out dist len = .ok (copyGo dist out len) := by
        unfold copyBack; rw [if_neg (by omega)]
      rw [hcb]
      exact ih'

theorem fixedHeader_size : fixedHeader.bits.size = 3 := by
  simp [fixedHeader, writeBits_size, BitWriter.empty]

/-- Any stream that starts with `fixedHeader`'s bits reads as a final fixed block. -/
theorem readHeader_fixedHeader {bs : ByteArray} {R : Array Bool}
    (hB : bs = (BitWriter.mk (fixedHeader.bits ++ R)).toBytes) :
    readHeader ⟨bs, 0⟩ = .ok (⟨true, .fixed⟩, ⟨bs, 3⟩) := by
  have e1 : bs = (BitWriter.mk ((BitWriter.empty.writeBits 1 1).bits ++
      (BitWriter.mk (lsbBits 1 2 ++ R)).bits)).toBytes := by
    rw [hB]; simp only [fixedHeader, writeBits_bits, Array.append_assoc]
  have e2 : bs = (BitWriter.mk (((BitWriter.empty.writeBits 1 1).writeBits 1 2).bits ++
      (BitWriter.mk R).bits)).toBytes := hB
  have hsz0 : (BitWriter.empty).bits.size = 0 := rfl
  have hsz1 : (BitWriter.empty.writeBits 1 1).bits.size = 1 := by
    simp [writeBits_size, BitWriter.empty]
  have hb0 := written_bits BitWriter.empty 1 1 ⟨lsbBits 1 2 ++ R⟩ 0 (by omega)
  rw [← e1, hsz0] at hb0
  obtain ⟨hlt, hbit⟩ := hb0
  have hr2 := readBits_written (BitWriter.empty.writeBits 1 1) 1 2 ⟨R⟩ (by decide)
  rw [← e2, hsz1] at hr2
  unfold readHeader
  rw [readBit_of_lt hlt]
  dsimp only
  rw [hbit, hr2]
  rfl

/-- **Fixed-Huffman round trip** (spec §3.4). A valid token list whose
    expansion fits the limit decodes back to that expansion. Fuel: every
    token takes at least 7 bits, so `8 * size + 1` covers one iteration
    per token; this is for `emitFixed` streams only, not the general P8 gap. -/
theorem decode_emitFixed (ts : List Token) (limit : Nat) (hv : Valid ts)
    (hl : (expand ts).size ≤ limit) : decode (emitFixed ts) limit = .ok ⟨expand ts⟩ := by
  obtain ⟨T, hT, hTs⟩ := foldl_emitToken_bits ts fixedHeader
  have hbs : emitFixed ts =
      (BitWriter.mk ((ts.foldl emitToken fixedHeader).bits ++ endBits)).toBytes := rfl
  have hh := readHeader_fixedHeader (bs := emitFixed ts) (R := T ++ endBits)
    (by rw [hbs, hT, Array.append_assoc])
  have hfuel : ts.length < 8 * (emitFixed ts).size + 1 := by
    rw [hbs, toBytes_size]
    simp only [hT, Array.size_append]
    omega
  have hloop := emitFixed_loop (emitFixed ts) limit ts fixedHeader #[] _ hbs hv hl hfuel
  rw [fixedHeader_size] at hloop
  unfold decode decodeFuel
  rw [decodeFuelLoop.eq_2, hh]
  simp only [bind, Except.bind, decodeBlockBody]
  rw [hloop]
  dsimp only
  rw [if_neg (by unfold expand at hl; omega), if_pos trivial]
  rfl

/-- The empty block: header, then symbol 256 (seven 0 bits), as Rust's
    `fixed_tests` decode. -/
example : (emitFixed []).data = #[0x03, 0x00] := by decide +kernel

/-- `abca` then a match of 8 at distance 3: the bytes zlib produces for
    `abcabcabcabc` (raw deflate, level 9), as in Rust's `fixed_tests`. -/
example : (emitFixed [.literal 97, .literal 98, .literal 99, .literal 97, .match 8 3]).data =
    #[0x4b, 0x4c, 0x4a, 0x4e, 0x84, 0x21, 0x00] := by decide +kernel

/-- The bounds: length 258, distance 32768, and 9-bit literals. Rust's
    `emit_fixed` writes the same bytes for these tokens. -/
example : (emitFixed [.literal 97, .match 258 1, .match 3 32768]).data =
    #[75, 28, 5, 192, 251, 255, 1] := by decide +kernel

example : (emitFixed [.literal 200, .literal 255, .literal 0, .match 227 24577,
    .match 257 32767]).data = #[59, 241, 159, 97, 4, 92, 0, 48, 226, 175, 255, 7, 0] := by
  decide +kernel

end EmitFixedProps

/-! ### M7b — Canonical codes (spec §3.1)

  `decodeGo` walks lengths `1, 2, …`, carrying `first`, which is exactly
  `nextCode` (RFC 1951's `next_code`). Symbol `s` of length `L` has code
  `C = nextCode L + rank`. At each shorter length `k`, the `k`-bit prefix of
  `C` is at least `nextCode k + countOf k`, because `nextCode` at least
  doubles per length (`nextCode_gap`), so the range test fails; at `L`, the
  test succeeds with offset `rank`, and `symbolsOf L` holds `s` there
  (`symbolsOf_rank`). The Kraft bound (`kraft ≤ 2 ^ 15`, true for every code
  the decoder accepts) gives `C < 2 ^ L`, so the `L` written bits are all of
  `C`. -/

section CanonicalProps
open BitWriter

theorem Nat.shiftRight_succ_bit (C m : Nat) :
    (C >>> (m+1)) * 2 + (if C.testBit m then 1 else 0) = C >>> m := by
  rw [Nat.shiftRight_eq_div_pow, Nat.shiftRight_eq_div_pow, Nat.testBit_eq_decide_div_mod_eq,
    Nat.pow_succ, ← Nat.div_div_eq_div_mul]
  have := Nat.div_add_mod (C / 2^m) 2
  have := Nat.mod_lt (C / 2^m) (by decide : 2 > 0)
  split <;> rename_i h <;> simp at h <;> omega

theorem foldl_countStep_eq (len : Nat) : ∀ (xs : List Nat) (acc : Nat),
    xs.foldl (fun acc l => if l = len then acc + 1 else acc) acc
      = acc + (xs.filter (fun l => l = len)).length := by
  intro xs
  induction xs with
  | nil => intro acc; simp
  | cons x xs ih =>
    intro acc
    simp only [List.foldl_cons, List.filter_cons]
    rw [ih]
    by_cases h : x = len <;> simp [h] <;> omega

theorem Array.toList_eq_map_range (ls : Array Nat) :
    ls.toList = (List.range ls.size).map (fun i => ls[i]!) := by
  apply List.ext_getElem
  · simp
  · intro i h1 h2
    simp at h1
    simp [List.getElem_map, List.getElem_range, h1]

theorem Code.countOf_eq_length (c : Code) (len : Nat) :
    c.countOf len = (c.symbolsOf len).length := by
  unfold Code.countOf Code.symbolsOf
  rw [foldl_countStep_eq, Array.toList_eq_map_range, List.filter_map, List.length_map, Nat.zero_add]
  rfl

theorem symbolsOf_rank (ls : Array Nat) (s : Nat) (hs : s < ls.size) :
    (Code.symbolsOf ⟨ls⟩ ls[s]!)[canonicalRank ls s]? = some s := by
  unfold Code.symbolsOf canonicalRank
  dsimp only
  obtain ⟨m, hm⟩ : ∃ m, ls.size = s + 1 + m := ⟨ls.size - (s + 1), by omega⟩
  rw [hm, List.range_add, List.range_succ, List.filter_append, List.filter_append,
    List.getElem?_append_left, List.getElem?_append_right (Nat.le_refl _), Nat.sub_self]
  · simp
  · simp

theorem rank_lt_countOf (ls : Array Nat) (s : Nat) (hs : s < ls.size) :
    canonicalRank ls s < Code.countOf ⟨ls⟩ ls[s]! := by
  rw [Code.countOf_eq_length]
  have := symbolsOf_rank ls s hs
  exact (List.getElem?_eq_some_iff.mp this).1

theorem nextCode_succ (c : Code) (k : Nat) (hk : 1 ≤ k) :
    nextCode c (k + 1) = (nextCode c k + c.countOf k) * 2 := by
  obtain ⟨j, rfl⟩ : ∃ j, k = j + 1 := ⟨k - 1, by omega⟩
  rfl

theorem nextCode_gap (c : Code) (k : Nat) (hk : 1 ≤ k) : ∀ d,
    (nextCode c k + c.countOf k) * 2 ^ (d + 1) ≤ nextCode c (k + 1 + d) := by
  intro d
  induction d with
  | zero => rw [nextCode_succ c k hk]; simp
  | succ d ih =>
    rw [show k + 1 + (d + 1) = (k + 1 + d) + 1 by omega, nextCode_succ c _ (by omega), Nat.pow_succ]
    rw [← Nat.mul_assoc]
    exact Nat.mul_le_mul_right 2 (Nat.le_trans ih (Nat.le_add_right _ _))

def kraftStep (c : Code) (acc len : Nat) : Nat :=
  if len = 0 then acc else acc + c.countOf len * 2 ^ (maxCodeLen - len)

theorem kraft_partial (c : Code) : ∀ l, 1 ≤ l → l ≤ maxCodeLen →
    (List.range (l + 1)).foldl (kraftStep c) 0
      = (nextCode c l + c.countOf l) * 2 ^ (maxCodeLen - l) := by
  intro l h1 h2
  induction l with
  | zero => omega
  | succ l ih =>
    rw [List.range_succ, List.foldl_append]
    simp only [List.foldl_cons, List.foldl_nil]
    rcases Nat.eq_zero_or_pos l with rfl | hl
    · simp [kraftStep, nextCode, maxCodeLen]
    · rw [ih hl (by omega), nextCode_succ c l hl]
      unfold kraftStep
      rw [if_neg (by omega)]
      rw [show maxCodeLen - l = (maxCodeLen - (l + 1)) + 1 by unfold maxCodeLen at *; omega,
        Nat.pow_succ]
      generalize 2 ^ (maxCodeLen - (l + 1)) = p
      simp only [Nat.add_mul, Nat.mul_assoc, Nat.mul_comm 2 p]

theorem foldl_kraftStep_mono (c : Code) : ∀ (xs : List Nat) (acc : Nat),
    acc ≤ xs.foldl (kraftStep c) acc := by
  intro xs
  induction xs with
  | nil => intro acc; simp
  | cons x xs ih =>
    intro acc
    simp only [List.foldl_cons]
    refine Nat.le_trans ?_ (ih _)
    unfold kraftStep; split <;> omega

theorem kraft_ge (c : Code) (l : Nat) (h1 : 1 ≤ l) (h2 : l ≤ maxCodeLen) :
    (nextCode c l + c.countOf l) * 2 ^ (maxCodeLen - l) ≤ c.kraft := by
  rw [← kraft_partial c l h1 h2]
  show _ ≤ (List.range (maxCodeLen + 1)).foldl (kraftStep c) 0
  obtain ⟨m, hm⟩ : ∃ m, maxCodeLen + 1 = (l + 1) + m := ⟨maxCodeLen - l, by omega⟩
  have e : List.range (maxCodeLen + 1) = List.range (l + 1) ++ (List.range m).map (fun x => l + 1 + x) := by
    rw [hm, List.range_add]
  rw [e, List.foldl_append]
  exact foldl_kraftStep_mono c _ _

theorem nextCode_count_le (c : Code) (hk : c.kraft ≤ 2 ^ maxCodeLen) (l : Nat) (h1 : 1 ≤ l)
    (h2 : l ≤ maxCodeLen) : nextCode c l + c.countOf l ≤ 2 ^ l := by
  have h := Nat.le_trans (kraft_ge c l h1 h2) hk
  rw [show 2 ^ maxCodeLen = 2 ^ l * 2 ^ (maxCodeLen - l) by rw [← Nat.pow_add]; congr 1; omega] at h
  exact Nat.le_of_mul_le_mul_right h (Nat.pow_pos (by decide))

theorem kraft_le_of_valid (c : Code)
    (hv : c.isComplete = true ∨ c.isValidDistance = true) : c.kraft ≤ 2 ^ maxCodeLen := by
  rcases hv with h | h
  · simp [Code.isComplete] at h; omega
  · simp [Code.isValidDistance, Code.isComplete] at h; omega

theorem decodeGo_canonical (c : Code) (r : BitReader) (C L s : Nat)
    (hbits : ∀ i < L, r.pos + i < r.size ∧ bitAt r.bytes (r.pos + i) = C.testBit (L - 1 - i))
    (hlo : nextCode c L ≤ C) (hhi : C - nextCode c L < c.countOf L)
    (hsym : (c.symbolsOf L)[C - nextCode c L]? = some s)
    (hgap : ∀ k, 1 ≤ k → k < L → (nextCode c k + c.countOf k) * 2 ^ (L - k) ≤ C) :
    ∀ n j fuel, j + 1 + n = L → n < fuel →
      decodeGo c (j + 1) (C >>> (L - j)) (nextCode c (j + 1)) ⟨r.bytes, r.pos + j⟩ fuel
        = .ok (s, ⟨r.bytes, r.pos + L⟩) := by
  intro n
  induction n with
  | zero =>
    intro j fuel hj hf
    obtain ⟨f, rfl⟩ : ∃ f, fuel = f + 1 := ⟨fuel - 1, by omega⟩
    obtain ⟨hlt, hb⟩ := hbits j (by omega)
    unfold decodeGo
    rw [readBit_of_lt (r := ⟨r.bytes, r.pos + j⟩) hlt]
    dsimp only
    rw [hb, show L - 1 - j = 0 by omega, show L - j = 0 + 1 by omega, Nat.shiftRight_succ_bit,
      Nat.shiftRight_zero, show j + 1 = L by omega, if_pos ⟨hlo, hhi⟩, hsym]
    simp only [Except.ok.injEq, Prod.mk.injEq, BitReader.mk.injEq, true_and]
    dsimp only [BitPos]; omega
  | succ n ih =>
    intro j fuel hj hf
    obtain ⟨f, rfl⟩ : ∃ f, fuel = f + 1 := ⟨fuel - 1, by omega⟩
    obtain ⟨hlt, hb⟩ := hbits j (by omega)
    unfold decodeGo
    rw [readBit_of_lt (r := ⟨r.bytes, r.pos + j⟩) hlt]
    dsimp only
    rw [hb, show L - j = (L - 1 - j) + 1 by omega, Nat.shiftRight_succ_bit]
    have hg := hgap (j + 1) (by omega) (by omega)
    have hcode : nextCode c (j + 1) + c.countOf (j + 1) ≤ C >>> (L - 1 - j) := by
      rw [Nat.shiftRight_eq_div_pow, show L - 1 - j = L - (j + 1) by omega]
      exact (Nat.le_div_iff_mul_le (Nat.pow_pos (by decide))).mpr hg
    have hn : ¬(nextCode c (j + 1) ≤ C >>> (L - 1 - j) ∧
        C >>> (L - 1 - j) - nextCode c (j + 1) < c.countOf (j + 1)) := by
      generalize C >>> (L - 1 - j) = x at hcode ⊢; omega
    rw [if_neg hn]
    have := ih (j + 1) f (by omega) (by omega)
    rw [show L - (j + 1) = L - 1 - j by omega, nextCode_succ c (j + 1) (by omega),
      ← Nat.add_assoc] at this
    exact this

/-- The general form: on any reader whose next `ls[s]` bits are symbol `s`'s
    canonical code, most significant first, `decodeSym ⟨ls⟩` returns `s` and
    consumes exactly those bits. -/
theorem decodeSym_of_canonical_bits {ls : Array Nat} {s : Nat} {r : BitReader}
    (hs : s < ls.size) (h0 : 0 < ls[s]) (h15 : ls[s] ≤ maxCodeLen)
    (hv : (⟨ls⟩ : Code).isComplete = true ∨ (⟨ls⟩ : Code).isValidDistance = true)
    (hbits : ∀ i < ls[s], r.pos + i < r.size ∧
      bitAt r.bytes (r.pos + i) = (canonicalCode ls s).1.testBit (ls[s] - 1 - i)) :
    decodeSym ⟨ls⟩ r = .ok (s, ⟨r.bytes, r.pos + ls[s]⟩) := by
  have hL : ls[s]! = ls[s] := getElem!_pos ls s hs
  unfold canonicalCode at hbits
  rw [hL] at hbits
  rw [← hL] at h0 h15 hbits ⊢
  generalize hLdef : ls[s]! = L at h0 h15 hbits ⊢
  have hrank := rank_lt_countOf ls s hs
  have hsym := symbolsOf_rank ls s hs
  rw [hLdef] at hrank hsym
  have hk := nextCode_count_le ⟨ls⟩ (kraft_le_of_valid _ hv) L (by omega) h15
  generalize hF : nextCode ⟨ls⟩ L = F at hbits hk
  generalize hR : canonicalRank ls s = R at hbits hrank hsym
  have hC : F + R < 2 ^ L := by omega
  have hgap : ∀ k, 1 ≤ k → k < L → (nextCode ⟨ls⟩ k + Code.countOf ⟨ls⟩ k) * 2 ^ (L - k) ≤ F + R := by
    intro k hk1 hkL
    have := nextCode_gap ⟨ls⟩ k hk1 (L - k - 1)
    rw [show k + 1 + (L - k - 1) = L by omega, show L - k - 1 + 1 = L - k by omega, hF] at this
    omega
  have hw := decodeGo_canonical ⟨ls⟩ r (F + R) L s hbits (by omega) (by omega)
    (by rw [hF, show F + R - F = R by omega]; exact hsym) hgap (L - 1) 0 maxCodeLen
    (by omega) (by unfold maxCodeLen at *; omega)
  rw [Nat.sub_zero, Nat.shiftRight_eq_div_pow, Nat.div_eq_of_lt hC, Nat.add_zero] at hw
  exact hw

/-- **Canonical codes decode.** For a length array the decoder accepts
    (complete, or valid as a distance code), wherever `canonicalCode ls s`
    is written with `writeCode` in a stream, `decodeSym ⟨ls⟩` there returns
    `s` and stops right after the code. Generalizes `fixedLit_code_decodes`
    to every valid code. -/
theorem decodeSym_canonical {ls : Array Nat} {bs : ByteArray} {w : BitWriter} {R : Array Bool}
    {s : Nat} (hs : s < ls.size) (h0 : 0 < ls[s]) (h15 : ls[s] ≤ maxCodeLen)
    (hv : (⟨ls⟩ : Code).isComplete = true ∨ (⟨ls⟩ : Code).isValidDistance = true)
    (hB : bs = (BitWriter.mk
      ((w.writeCode (canonicalCode ls s).1 (canonicalCode ls s).2).bits ++ R)).toBytes) :
    decodeSym ⟨ls⟩ ⟨bs, w.bits.size⟩
      = .ok (s, ⟨bs, (w.writeCode (canonicalCode ls s).1 (canonicalCode ls s).2).bits.size⟩) := by
  have hL : (canonicalCode ls s).2 = ls[s] := getElem!_pos ls s hs
  have hsz : (w.writeCode (canonicalCode ls s).1 (canonicalCode ls s).2).bits.size
      = w.bits.size + ls[s] := by
    rw [writeCode_eq, writeBits_size, hL]
  rw [hsz]
  subst hB
  apply decodeSym_of_canonical_bits hs h0 h15 hv
  intro i hi
  refine ⟨?_, ?_⟩
  · show w.bits.size + i < (BitWriter.mk _).toBytes.size * 8
    rw [toBytes_size, Array.size_append, hsz]
    omega
  · show bitAt _ (w.bits.size + i) = _
    rw [← hL]
    exact bitAt_writeCode w (canonicalCode ls s).1 (canonicalCode ls s).2 ⟨R⟩ i (by rw [hL]; exact hi)

/-- `canonicalCode` reproduces RFC 1951 §3.2.6's fixed literal/length codes,
    so the fixed tables are an instance of the canonical construction.
    Kernel evaluation, 288 cases. -/
theorem canonicalCode_fixedLit :
    ∀ s, s < 288 → canonicalCode fixedLitLen.lengths s = fixedLitCode s := by
  decide +kernel

/-- Likewise the fixed distance code: code = symbol, 5 bits. -/
theorem canonicalCode_fixedDist :
    ∀ s, s < 32 → canonicalCode fixedDist.lengths s = (s, 5) := by
  decide +kernel

end CanonicalProps

/-! ### Model compressor (spec §3.6) -/

/-- The headline round trip: whichever encoding `compress` keeps, the
    decoder returns the input, for every finder. -/
theorem decode_compress (find : Finder) (x : ByteArray) (limit : Nat) (h : x.size ≤ limit) :
    decode (compress find x) limit = .ok x := by
  unfold compress
  dsimp only
  split
  · have he := expand_compressTokens find x.data
    have hf := decode_emitFixed (compressTokens find x.data) limit
      (compressTokens_valid find x.data) (by rw [he]; exact h)
    rw [hf, he]
  · exact decode_encodeStored x limit h

end Deflate
