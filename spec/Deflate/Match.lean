/-
  Deflate.Match — the model matcher (spec §3.2).

  The finder is an untrusted oracle: `compressTokens` re-checks every
  candidate with `accept` and falls back to a literal, so its theorems hold
  for every `find`. Rust counterpart: `matcher.rs`, whose hash-chain finder
  performs the same acceptance check.
-/
import Deflate.Tokens

namespace Deflate

/-- A candidate `(len, dist)` for a match at position `i`, or none. -/
abbrev Finder := Array UInt8 → Nat → Option (Nat × Nat)

/-- The acceptance check of spec §3.2: the bounds, then byte equality
    `x[i+k] = x[i+k-dist]` for every `k < len`. -/
def accept (x : Array UInt8) (i len dist : Nat) : Bool :=
  decide (3 ≤ len) && decide (len ≤ 258) && decide (1 ≤ dist) &&
    decide (dist ≤ 32768) && decide (dist ≤ i) && decide (i + len ≤ x.size) &&
    (List.range len).all fun k => x[i + k]! == x[i + k - dist]!

theorem accept_len_pos {x : Array UInt8} {i len dist : Nat}
    (h : accept x i len dist = true) : 0 < len := by
  simp only [accept, Bool.and_eq_true, decide_eq_true_eq] at h
  omega

/-- Tokens for `x` from position `i` on. -/
def compressFrom (find : Finder) (x : Array UInt8) (i : Nat) : List Token :=
  if h : i < x.size then
    match find x i with
    | some (len, dist) =>
      if hacc : accept x i len dist = true then
        .match len dist :: compressFrom find x (i + len)
      else
        .literal x[i] :: compressFrom find x (i + 1)
    | none => .literal x[i] :: compressFrom find x (i + 1)
  else []
termination_by x.size - i
decreasing_by
  all_goals first
    | omega
    | (have := accept_len_pos hacc; omega)

/-- Greedy tokenization of `x` driven by `find`. -/
def compressTokens (find : Finder) (x : Array UInt8) : List Token :=
  compressFrom find x 0

end Deflate
