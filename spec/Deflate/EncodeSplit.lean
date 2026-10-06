import Deflate.Properties

namespace Deflate
open BitReader

/-- Untrusted Rust `SplitFor`: receives at most the next `blockTokens` tokens. -/
abbrev SplitFor := List Token → Option Nat

/-- Accept only positive requests no greater than `blockTokens`. -/
def checkedSplit (sf : SplitFor) (ts : List Token) : Nat :=
  match sf (ts.take blockTokens) with
  | some n => if 1 ≤ n ∧ n ≤ blockTokens then n else blockTokens
  | none => blockTokens

/-- Cap the checked request to the remaining token count. -/
def splitCount (sf : SplitFor) (ts : List Token) : Nat :=
  min (checkedSplit sf ts) ts.length

theorem checkedSplit_bounds (sf : SplitFor) (ts : List Token) :
    1 ≤ checkedSplit sf ts ∧ checkedSplit sf ts ≤ blockTokens := by
  unfold checkedSplit
  split
  · split
    · assumption
    · exact ⟨by decide, Nat.le_refl _⟩
  · exact ⟨by decide, Nat.le_refl _⟩

/-- A valid callback request is used unchanged before capping. -/
theorem checkedSplit_accept (sf : SplitFor) (ts : List Token) (n : Nat)
    (h : sf (ts.take blockTokens) = some n) (hn : 1 ≤ n ∧ n ≤ blockTokens) :
    checkedSplit sf ts = n := by
  simp only [checkedSplit, h, if_pos hn]

/-- Every invalid callback request falls back to the default. -/
theorem checkedSplit_reject (sf : SplitFor) (ts : List Token) (n : Nat)
    (h : sf (ts.take blockTokens) = some n) (hn : ¬ (1 ≤ n ∧ n ≤ blockTokens)) :
    checkedSplit sf ts = blockTokens := by
  simp only [checkedSplit, h, if_neg hn]

theorem splitCount_progress (sf : SplitFor) (ts : List Token)
    (h : ¬ ts.length ≤ splitCount sf ts) :
    (ts.drop (splitCount sf ts)).length < ts.length := by
  have := checkedSplit_bounds sf ts
  simp only [splitCount, List.length_drop] at *
  omega

/-- One shared writer; exactly the last chunk (including empty input) is final. -/
def emitSplitBlocksGo (sf : SplitFor) (lf : LengthsFor) (w : BitWriter)
    (ts : List Token) : BitWriter :=
  if ts.length ≤ splitCount sf ts then emitBlock lf w true ts
  else emitSplitBlocksGo sf lf (emitBlock lf w false (ts.take (splitCount sf ts)))
    (ts.drop (splitCount sf ts))
termination_by ts.length
decreasing_by exact splitCount_progress sf ts (by assumption)

def emitSplitBlocks (sf : SplitFor) (lf : LengthsFor) (ts : List Token) : ByteArray :=
  (emitSplitBlocksGo sf lf BitWriter.empty ts).toBytes

/-- `emitSplitBlocksGo` only appends. -/
theorem emitSplitBlocksGo_bits (sf : SplitFor) (lf : LengthsFor) (w : BitWriter) (ts : List Token) :
    ∃ T, (emitSplitBlocksGo sf lf w ts).bits = w.bits ++ T := by
  induction w, ts using emitSplitBlocksGo.induct sf lf with
  | case1 w ts h =>
    obtain ⟨T, hT, _⟩ := emitBlock_bits lf w true ts
    exact ⟨T, by rw [emitSplitBlocksGo.eq_1, if_pos h, hT]⟩
  | case2 w ts h ih =>
    obtain ⟨T1, hT1, _⟩ := emitBlock_bits lf w false (ts.take (splitCount sf ts))
    obtain ⟨T2, hT2⟩ := ih
    exact ⟨T1 ++ T2, by rw [emitSplitBlocksGo.eq_1, if_neg h, hT2, hT1, Array.append_assoc]⟩

/-- The induction behind `decode_emitSplitBlocks`, over `emitSplitBlocksGo`'s chunks:
    started at the end of the blocks already written (`w`), with any output
    `out` before them (matches may reach back into it), the decoder loop
    decodes the rest. Every block is at least 3 bits, so one unit of fuel
    per bit still to read is enough. -/
theorem decodeFuelLoop_emitSplitBlocksGo (sf : SplitFor) (lf : LengthsFor) (bs : ByteArray) (limit : Nat) :
    ∀ (w : BitWriter) (ts : List Token), bs = (emitSplitBlocksGo sf lf w ts).toBytes →
    ∀ (out : Array UInt8) (fuel : Nat), ValidFrom out ts →
    (ts.foldl expandStep out).size ≤ limit → 8 * bs.size - w.bits.size < fuel →
    decodeFuelLoop bs limit ⟨bs, w.bits.size⟩ out fuel = .ok ⟨ts.foldl expandStep out⟩ := by
  intro w ts
  induction w, ts using emitSplitBlocksGo.induct sf lf with
  | case1 w ts h =>
    intro hbs out fuel hv hl hf
    rw [emitSplitBlocksGo.eq_1, if_pos h] at hbs
    obtain ⟨bt, hh, hbody⟩ := decodeBlock_emitBlock lf (bs := bs) (w := w) (final := true) (R := #[])
      (by rw [hbs, Array.append_empty]) hv hl
    obtain ⟨k, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by omega⟩
    rw [decodeFuelLoop.eq_2, hh]
    simp only [bind, Except.bind]
    rw [hbody]
    dsimp only
    rw [if_neg (by omega), if_pos trivial]
  | case2 w ts h ih =>
    intro hbs out fuel hv hl hf
    rw [emitSplitBlocksGo.eq_1, if_neg h] at hbs
    have hsplit := List.take_append_drop (splitCount sf ts) ts
    rw [← hsplit, validFrom_append] at hv
    rw [← hsplit, List.foldl_append] at hl
    obtain ⟨T, hT⟩ := emitSplitBlocksGo_bits sf lf (emitBlock lf w false (ts.take (splitCount sf ts)))
      (ts.drop (splitCount sf ts))
    obtain ⟨T1, hT1, hT1s⟩ := emitBlock_bits lf w false (ts.take (splitCount sf ts))
    have hgrow := foldl_expandStep_size (ts.drop (splitCount sf ts))
      ((ts.take (splitCount sf ts)).foldl expandStep out)
    obtain ⟨bt, hh, hbody⟩ := decodeBlock_emitBlock lf (bs := bs) (limit := limit) (w := w) (final := false) (R := T)
      (by rw [hbs, ← hT]) hv.1 (by omega)
    have htot := bits_le_toBytes (emitSplitBlocksGo sf lf (emitBlock lf w false (ts.take (splitCount sf ts)))
      (ts.drop (splitCount sf ts)))
    rw [← hbs, hT, Array.size_append, hT1, Array.size_append] at htot
    obtain ⟨k, rfl⟩ : ∃ k, fuel = k + 1 := ⟨fuel - 1, by omega⟩
    rw [decodeFuelLoop.eq_2, hh]
    simp only [bind, Except.bind]
    rw [hbody]
    dsimp only
    rw [if_neg (by omega)]
    simp only [Bool.false_eq_true, if_false]
    have := ih hbs ((ts.take (splitCount sf ts)).foldl expandStep out) k hv.2 hl
      (by rw [hT1, Array.size_append]; omega)
    rw [this, ← List.foldl_append, hsplit]

/-- **Multi-block round trip** (spec §3.3). For every callback and `LengthsFor`, a
    valid token list whose expansion fits the limit decodes back to that
    expansion, whatever mix of fixed and dynamic blocks `emitSplitBlocks` chose.
    `Valid` is about the whole list, so a match may reach back into an
    earlier block, as RFC 1951 allows. -/
theorem decode_emitSplitBlocks (sf : SplitFor) (lf : LengthsFor) (ts : List Token) (limit : Nat) (hv : Valid ts)
    (hl : (expand ts).size ≤ limit) :
    decode (emitSplitBlocks sf lf ts) limit = .ok ⟨expand ts⟩ := by
  unfold decode decodeFuel
  have := decodeFuelLoop_emitSplitBlocksGo sf lf (emitSplitBlocks sf lf ts) limit BitWriter.empty ts rfl #[]
    (8 * (emitSplitBlocks sf lf ts).size + 1) hv hl (by omega)
  exact this

/-- The callback view never exceeds Rust's block-token bound. -/
theorem splitView_length (ts : List Token) :
    (ts.take blockTokens).length ≤ blockTokens := by
  simp only [List.length_take]
  exact Nat.min_le_left _ _

theorem splitCount_bounds (sf : SplitFor) (ts : List Token) :
    splitCount sf ts ≤ ts.length ∧ splitCount sf ts ≤ blockTokens := by
  have := checkedSplit_bounds sf ts
  unfold splitCount
  exact ⟨Nat.min_le_right _ _, Nat.le_trans (Nat.min_le_left _ _) this.2⟩

/-- Finality means exactly that the selected chunk exhausts the input. -/
theorem splitCount_final (sf : SplitFor) (ts : List Token) :
    ts.length ≤ splitCount sf ts ↔ ts.drop (splitCount sf ts) = [] := by
  rw [List.drop_eq_nil_iff]

/-- With no request, the checked size is exactly the existing default. -/
theorem splitCount_none (ts : List Token) :
    splitCount (fun _ => none) ts = min blockTokens ts.length := by
  rfl

/-- Default splitting preserves the writer's bits, even after a prefix. -/
theorem emitSplitBlocksGo_none (lf : LengthsFor) (w : BitWriter) (ts : List Token) :
    emitSplitBlocksGo (fun _ => none) lf w ts = emitBlocksGo lf w ts := by
  induction w, ts using emitBlocksGo.induct lf with
  | case1 w ts h =>
    rw [emitSplitBlocksGo.eq_1, emitBlocksGo.eq_1, if_pos h]
    rw [splitCount_none, Nat.min_eq_right h, if_pos (Nat.le_refl _)]
  | case2 w ts h ih =>
    rw [emitSplitBlocksGo.eq_1, emitBlocksGo.eq_1, if_neg h]
    have hm : min blockTokens ts.length = blockTokens := Nat.min_eq_left (by omega)
    rw [splitCount_none, hm, if_neg h]
    exact ih

/-- Default splitting is byte-for-byte the existing emitter, for every heuristic. -/
theorem emitSplitBlocks_none (lf : LengthsFor) (ts : List Token) :
    emitSplitBlocks (fun _ => none) lf ts = emitBlocks lf ts := by
  unfold emitSplitBlocks emitBlocks
  rw [emitSplitBlocksGo_none]

/-- Kernel-evaluated rejection of a zero request. -/
example : checkedSplit (fun _ => some 0) [] = 16384 := by decide

/-- Kernel-evaluated rejection of an oversized request. -/
example : checkedSplit (fun _ => some 16385) [] = 16384 := by decide

/-- Keep the compressed blocks only when strictly smaller; ties use stored. -/
def compressSplit (find : Finder) (sf : SplitFor) (lf : LengthsFor) (x : ByteArray) : ByteArray :=
  let b := emitSplitBlocks sf lf (compressTokens find x.data)
  let s := encodeStored x
  if b.size < s.size then b else s

theorem decode_compressSplit (find : Finder) (sf : SplitFor) (lf : LengthsFor)
    (x : ByteArray) (limit : Nat) (h : x.size ≤ limit) :
    decode (compressSplit find sf lf x) limit = .ok x := by
  unfold compressSplit
  dsimp only
  split
  · have he := expand_compressTokens find x.data
    have hb := decode_emitSplitBlocks sf lf (compressTokens find x.data) limit
      (compressTokens_valid find x.data) (by rw [he]; exact h)
    rw [hb, he]
  · exact decode_encodeStored x limit h

end Deflate
