/-
  Deflate.EncodeDynamic — the dynamic-Huffman block header on the encoder
  side (RFC 1951 §3.2.7, spec M7b §3.2).

  The code lengths of the literal/length and distance codes are sent
  run-length encoded over the code-length (CL) alphabet: symbols 0–15 are
  a length, 16 repeats the previous length 3–6 times (2 extra bits), 17
  writes 3–10 zeros (3 extra bits) and 18 writes 11–138 zeros (7 extra
  bits). `rleLengths` is the run-length encoder, `ClSym.apply` is what the
  decoder's `readCodeLengths` does with one symbol, and `emitHeader` writes
  HLIT, HDIST, HCLEN, the CL lengths in `clOrder`, and the RLE symbols
  under the canonical CL code. Rust counterparts: `huffman_build.rs`
  (`rle_lengths`) and `encode_dynamic.rs` (`emit_dynamic_block`); the two
  must agree bit for bit (`EMITDYN` oracle).
-/
import Deflate.BitWriter
import Deflate.Block
import Deflate.Canonical
import Deflate.EncodeFixed

namespace Deflate

/-- One code-length-alphabet symbol. The argument of `rep16`, `zeros17`
    and `zeros18` is the extra-bits value (the count minus 3, 3 and 11),
    as in Rust's `ClSym`. -/
inductive ClSym where
  | len (v : Nat)
  | rep16 (n : Nat)
  | zeros17 (n : Nat)
  | zeros18 (n : Nat)
  deriving Repr, DecidableEq, Inhabited

namespace ClSym

/-- The CL alphabet symbol, 0..18. -/
def sym : ClSym → Nat
  | len v => v
  | rep16 _ => 16
  | zeros17 _ => 17
  | zeros18 _ => 18

/-- The extra bits as `(value, width)`. -/
def extra : ClSym → Nat × Nat
  | len _ => (0, 0)
  | rep16 n => (n, 2)
  | zeros17 n => (n, 3)
  | zeros18 n => (n, 7)

/-- What the decoder (`readCodeLengths.go`) appends for this symbol. -/
def apply (acc : Array Nat) : ClSym → Array Nat
  | len v => acc.push v
  | rep16 n => acc ++ Array.replicate (3 + n) (acc.back?.getD 0)
  | zeros17 n => acc ++ Array.replicate (3 + n) 0
  | zeros18 n => acc ++ Array.replicate (11 + n) 0

end ClSym

/-- Expand an RLE symbol list back into code lengths. -/
def expandRle (syms : List ClSym) : Array Nat := syms.foldl ClSym.apply #[]

/-- A run of `n` zeros: 18s of up to 138 while at least 11 remain, then
    one 17 if at least 3 remain, then literal zeros. -/
def zerosRun (n : Nat) : List ClSym :=
  if 11 ≤ n then .zeros18 (min n 138 - 11) :: zerosRun (n - min n 138)
  else if 3 ≤ n then [.zeros17 (n - 3)]
  else List.replicate n (.len 0)
termination_by n
decreasing_by omega

/-- `n` further copies of a nonzero `v` already written once: 16s of up to
    6 while at least 3 remain, then literal `v`s. -/
def repRun (v n : Nat) : List ClSym :=
  if 3 ≤ n then .rep16 (min n 6 - 3) :: repRun v (n - min n 6)
  else List.replicate n (.len v)
termination_by n
decreasing_by omega

/-- A maximal run of `n ≥ 1` copies of `v`. -/
def runSyms (v n : Nat) : List ClSym :=
  if v = 0 then zerosRun n else .len v :: repRun v (n - 1)

/-- Run-length encode a list of lengths, one maximal run at a time. -/
def rleList : List Nat → List ClSym
  | [] => []
  | v :: rest =>
    let k := (rest.takeWhile (· == v)).length
    runSyms v (k + 1) ++ rleList (rest.drop k)
termination_by l => l.length
decreasing_by simp; omega

/-- Run-length encode code lengths (spec "Shared formats", RLE). Callers
    pass `lit ++ dist`, so runs may cross the boundary. Rust: `rle_lengths`. -/
def rleLengths (ls : Array Nat) : List ClSym := rleList ls.toList

/-- `clCount cl k`: one more than the last position `i < k` in `clOrder`
    with `cl[clOrder[i]] ≠ 0`, or 0 if there is none. -/
def clCount (cl : Array Nat) : Nat → Nat
  | 0 => 0
  | k + 1 => if cl[clOrder[k]!]! ≠ 0 then k + 1 else clCount cl k

/-- HCLEN: trailing zero CL lengths (in `clOrder`) trimmed, at least 4
    kept, minus 4. -/
def hclenOf (cl : Array Nat) : Nat := max 4 (clCount cl 19) - 4

/-- One RLE symbol: its canonical CL code, then its extra bits. -/
def writeClSym (cl : Array Nat) (w : BitWriter) (s : ClSym) : BitWriter :=
  (w.writeCode (canonicalCode cl s.sym).1 (canonicalCode cl s.sym).2).writeBits s.extra.1 s.extra.2

/-- The CL lengths `cl[clOrder[i]]` for `i` from `i` up to `ncode`, 3 bits
    each; the writing twin of `readCLLens.go`. -/
def writeCLLensFrom (cl : Array Nat) (ncode i : Nat) (w : BitWriter) : BitWriter :=
  if i < ncode then writeCLLensFrom cl ncode (i + 1) (w.writeBits cl[clOrder[i]!]! 3) else w
termination_by ncode - i

/-- The CL lengths for the first `hclenOf cl + 4` entries of `clOrder`,
    3 bits each. -/
def writeCLLens (cl : Array Nat) (w : BitWriter) : BitWriter :=
  writeCLLensFrom cl (hclenOf cl + 4) 0 w

/-- The dynamic header after BFINAL/BTYPE: HLIT, HDIST, HCLEN, the CL
    lengths, then the RLE of `lit ++ dist` under the CL code. `lit`,
    `dist` and `cl` are used as given (no trimming); `cl` is indexed by CL
    symbol. -/
def emitHeader (w : BitWriter) (lit dist cl : Array Nat) : BitWriter :=
  let w := ((w.writeBits (lit.size - 257) 5).writeBits (dist.size - 1) 5).writeBits (hclenOf cl) 4
  (rleLengths (lit ++ dist)).foldl (writeClSym cl) (writeCLLens cl w)

/-! ### Dynamic blocks and the block stream (M7b spec §3.3) -/

/-- Emit one token under the codes `lc` (literal/length) and `dc`
    (distance), each giving a symbol's `(code, length)`: a literal's code, or
    a match's length symbol, length extra bits, distance symbol and distance
    extra bits. With `lc := fixedLitCode` and `dc := (·, 5)` this is M7a's
    `emitToken` (`Properties.emitToken_eq_with`). -/
def emitTokenWith (lc dc : Nat → Nat × Nat) (w : BitWriter) : Token → BitWriter
  | .literal b => w.writeCode (lc b.toNat).1 (lc b.toNat).2
  | .match len dist =>
    let l := lengthSym len   -- (symbol, extra value, extra bits)
    let d := distSym dist
    (((w.writeCode (lc l.1).1 (lc l.1).2).writeBits l.2.1 l.2.2).writeCode
      (dc d.1).1 (dc d.1).2).writeBits d.2.1 d.2.2

/-- Every symbol a token needs has a nonzero length: a literal's byte, or a
    match's length symbol (in `lit`) and distance symbol (in `dist`). An
    index past the end reads as 0, so this also bounds the symbol. -/
def tokenCoded (lit dist : Array Nat) : Token → Bool
  | .literal b => 0 < lit[b.toNat]!
  | .match len d => 0 < lit[(lengthSym len).1]! && 0 < dist[(distSym d).1]!

/-- The lengths are usable for a dynamic block over `ts` (spec "Shared
    formats", Validity): sizes in range, lit/dist lengths ≤ 15 and CL
    lengths ≤ 7, `lit` and `cl` complete, `dist` a valid distance code,
    symbol 256 and every symbol `ts` uses coded, and every CL symbol the RLE
    of `lit ++ dist` uses coded. Rust: `valid_lengths`. -/
def validLengths (lit dist cl : Array Nat) (ts : List Token) : Bool :=
  (257 ≤ lit.size && lit.size ≤ 286) && (1 ≤ dist.size && dist.size ≤ 30) && cl.size == 19 &&
  lit.all (· ≤ 15) && dist.all (· ≤ 15) && cl.all (· ≤ 7) &&
  (⟨lit⟩ : Code).isComplete && (⟨dist⟩ : Code).isValidDistance && (⟨cl⟩ : Code).isComplete &&
  0 < lit[256]! && ts.all (tokenCoded lit dist) &&
  (rleLengths (lit ++ dist)).all (fun s => 0 < cl[s.sym]!)

/-- Per-block code lengths `(lit, dist, cl)`, `cl` indexed by CL symbol, or
    `none` for a fixed block. Untrusted, like `Finder`: every result is
    checked by `validLengths`. Rust: `lengths_for` (a heuristic). -/
abbrev LengthsFor := List Token → Option (Array Nat × Array Nat × Array Nat)

/-- One dynamic block appended to `w`: BFINAL = `final`, BTYPE = 10, the
    header (`emitHeader`), the tokens under the canonical codes of `lit` and
    `dist`, then symbol 256. Lengths are used as given; callers check
    `validLengths`. Rust: `emit_dynamic_block`. -/
def emitDynamicBlock (w : BitWriter) (final : Bool) (lit dist cl : Array Nat)
    (ts : List Token) : BitWriter :=
  let w := emitHeader ((w.writeBits (if final then 1 else 0) 1).writeBits 2 2) lit dist cl
  let w := ts.foldl (emitTokenWith (canonicalCode lit) (canonicalCode dist)) w
  w.writeCode (canonicalCode lit 256).1 (canonicalCode lit 256).2

/-- Exact bit size of `emitFixedBlock` over `ts`. Rust: `fixed_bits`. -/
def fixedBits (ts : List Token) : Nat :=
  ts.foldl (fun n t => n + match t with
    | .literal b => (fixedLitCode b.toNat).2
    | .match len d =>
      (fixedLitCode (lengthSym len).1).2 + (lengthSym len).2.2 + 5 + (distSym d).2.2)
    (3 + (fixedLitCode 256).2)

/-- Exact bit size of `emitDynamicBlock` with these lengths over `ts`.
    Rust: `dynamic_bits`. -/
def dynBits (lit dist cl : Array Nat) (ts : List Token) : Nat :=
  let hdr := 3 + 14 + 3 * (hclenOf cl + 4)
  let rle := (rleLengths (lit ++ dist)).foldl (fun n s => n + cl[s.sym]! + s.extra.2) 0
  ts.foldl (fun n t => n + match t with
    | .literal b => lit[b.toNat]!
    | .match len d => lit[(lengthSym len).1]! + (lengthSym len).2.2 +
        dist[(distSym d).1]! + (distSym d).2.2)
    (hdr + rle + lit[256]!)

/-- One block (spec "Shared formats", per-block choice): dynamic iff
    `lf ts` gives lengths, they pass `validLengths`, and the dynamic block is
    strictly smaller; fixed otherwise. Rust: `emit_block`. -/
def emitBlock (lf : LengthsFor) (w : BitWriter) (final : Bool) (ts : List Token) : BitWriter :=
  match lf ts with
  | some (lit, dist, cl) =>
    if validLengths lit dist cl ts && dynBits lit dist cl ts < fixedBits ts then
      emitDynamicBlock w final lit dist cl ts
    else emitFixedBlock w final ts
  | none => emitFixedBlock w final ts

/-- Tokens per block (spec §3.3). Rust: `BLOCK_TOKENS`. -/
def blockTokens : Nat := 16384

/-- The blocks for `ts`, appended to `w`: chunks of `blockTokens`, the last
    (or only, possibly empty) chunk final. -/
def emitBlocksGo (lf : LengthsFor) (w : BitWriter) (ts : List Token) : BitWriter :=
  if ts.length ≤ blockTokens then emitBlock lf w true ts
  else emitBlocksGo lf (emitBlock lf w false (ts.take blockTokens)) (ts.drop blockTokens)
termination_by ts.length
decreasing_by simp [blockTokens] at *; omega

/-- The block stream for `ts`: blocks share one writer, and only the end is
    padded to a byte. Rust: `emit_blocks`. -/
def emitBlocks (lf : LengthsFor) (ts : List Token) : ByteArray :=
  (emitBlocksGo lf BitWriter.empty ts).toBytes

end Deflate
