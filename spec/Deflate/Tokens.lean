/-
  Deflate.Tokens — the LZ77 token stream the compressor produces (spec §3.1).

  `expand` replays tokens with the decoder's own `copyGo`, so the emitter's
  round-trip theorem reuses the decoder's copy semantics rather than a second
  definition of "back-reference". Rust counterpart: `tokens.rs`.
-/
import Deflate.LZ77

namespace Deflate

/-- A literal byte, or a back-reference of `len` bytes from `dist` back. -/
inductive Token
  | literal (b : UInt8)
  | «match» (len dist : Nat)
  deriving Repr, DecidableEq, Inhabited

/-- Replay one token: a literal is pushed, a match is the decoder's copy. -/
def expandStep (out : Array UInt8) : Token → Array UInt8
  | .literal b => out.push b
  | .match len dist => copyGo dist out len

/-- The bytes a token list stands for. -/
def expand (ts : List Token) : Array UInt8 := ts.foldl expandStep #[]

/-- A token is encodable after `outSize` bytes of output: a match must fit
    the fixed length/distance codes (RFC 1951 §3.2.5) and reach no further
    back than the output so far, which is exactly what `copyBack` accepts. -/
def Token.valid (outSize : Nat) : Token → Prop
  | .literal _ => True
  | .match len dist => 3 ≤ len ∧ len ≤ 258 ∧ 1 ≤ dist ∧ dist ≤ 32768 ∧ dist ≤ outSize

/-- Every token is valid against the output its predecessors produced,
    starting from `out`. -/
def ValidFrom : Array UInt8 → List Token → Prop
  | _, [] => True
  | out, t :: ts => t.valid out.size ∧ ValidFrom (expandStep out t) ts

/-- Every token is valid against the size of `expand` of its prefix. -/
def Valid (ts : List Token) : Prop := ValidFrom #[] ts

end Deflate
