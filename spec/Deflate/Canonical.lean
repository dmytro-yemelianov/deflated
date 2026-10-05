/-
  Deflate.Canonical — canonical Huffman codes on the encoder side
  (RFC 1951 §3.2.2, spec M7b §3.1).

  Given code lengths, RFC 1951 §3.2.2 fixes every code:
  `bl_count[l]` symbols have length `l`, the first code of length `l` is
  `next_code[l] = (next_code[l-1] + bl_count[l-1]) << 1` with
  `bl_count[0] = 0`, and codes of one length go to symbols in increasing
  symbol order. `canonicalCode ls s` is symbol `s`'s `(code, length)` under
  that rule, computed per symbol: the first code of its length plus its rank
  among the symbols of that length.

  `nextCode` is literally the `first` that the decoder `decodeGo` carries
  from length to length, which is what `Properties.decodeSym_canonical`
  exploits. Rust counterpart: `huffman.rs`, encoder side.
-/
import Deflate.Huffman

namespace Deflate

/-- `next_code[l]` of RFC 1951 §3.2.2 for the code `c`: the first code of
    length `l`. `next_code[0]` and `next_code[1]` are 0 (`bl_count[0] = 0`);
    each further length doubles the previous one's first code plus count. -/
def nextCode (c : Code) : Nat → Nat
  | 0 => 0
  | 1 => 0
  | l + 2 => (nextCode c (l + 1) + c.countOf (l + 1)) * 2

/-- Symbol `s`'s position among the symbols with its length: the number of
    smaller symbols with the same length. -/
def canonicalRank (ls : Array Nat) (s : Nat) : Nat :=
  ((List.range s).filter (fun t => ls[t]! = ls[s]!)).length

/-- Symbol `s`'s canonical code as `(code, length)`, to be written MSB first
    with `BitWriter.writeCode`. Meaningful when `ls[s] > 0`; an unused symbol
    gets length 0, so writing it writes nothing. Rust: `canonical_code`. -/
def canonicalCode (ls : Array Nat) (s : Nat) : Nat × Nat :=
  (nextCode ⟨ls⟩ ls[s]! + canonicalRank ls s, ls[s]!)

end Deflate
