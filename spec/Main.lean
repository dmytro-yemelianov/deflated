import Deflate
import Deflate.Gzip
import Deflate.Zip

open Deflate

def hexDigit? (c : Char) : Option Nat :=
  if '0' ≤ c ∧ c ≤ '9' then some (c.toNat - '0'.toNat)
  else if 'a' ≤ c ∧ c ≤ 'f' then some (c.toNat - 'a'.toNat + 10)
  else if 'A' ≤ c ∧ c ≤ 'F' then some (c.toNat - 'A'.toNat + 10)
  else none

def ofHex (s : String) : Option ByteArray := do
  let cs := s.toList
  if cs.length % 2 ≠ 0 then none else
  let rec go : List Char → Option (List UInt8)
    | [] => some []
    | a :: b :: rest => do
        let hi ← hexDigit? a
        let lo ← hexDigit? b
        let tl ← go rest
        pure (UInt8.ofNat (hi * 16 + lo) :: tl)
    | _ => none
  (go cs).map (fun bs => ⟨bs.toArray⟩)

def toHex (bs : ByteArray) : String :=
  let digits := "0123456789abcdef".toList
  bs.toList.foldl (fun acc b =>
    acc.push (digits[b.toNat / 16]!) |>.push (digits[b.toNat % 16]!)) ""

def errName : DecErr → String
  | .unexpectedEof       => "unexpectedEof"
  | .invalidBlockType    => "invalidBlockType"
  | .invalidStoredLength => "invalidStoredLength"
  | .invalidHuffmanTree  => "invalidHuffmanTree"
  | .invalidCode         => "invalidCode"
  | .invalidDistance     => "invalidDistance"
  | .invalidLength       => "invalidLength"
  | .outputLimitExceeded => "outputLimitExceeded"
  | .fuelExhausted       => "fuelExhausted"

def decodeAndFormat (limit : Nat) (hx : String) : String :=
  match ofHex hx with
  | none => "ERR badHex"
  | some bs =>
    match Deflate.decode bs limit with
    | .ok out => s!"OK {toHex out}"
    | .error e => s!"ERR {errName e}"

/-- Strict decimal: digits only, at most 65535 (the Rust oracle parses `u16`). -/
def decU16? (s : String) : Option Nat :=
  if s.isEmpty ∨ !s.all Char.isDigit then none else
  let n := s.foldl (fun acc c => acc * 10 + (c.toNat - '0'.toNat)) 0
  if n ≤ 65535 then some n else none

/-- One oracle token: `l:HH` (literal byte, two hex digits) or
    `m:LEN:DIST` (decimal). Rust: `parse_token` in `vdeflate`. -/
def parseToken? (s : String) : Option Token :=
  match s.splitOn ":" with
  | ["l", h] => if h.length = 2 then (ofHex h).bind (fun b => b.data[0]?.map .literal) else none
  | ["m", l, d] => do
    let len ← decU16? l
    let dist ← decU16? d
    pure (.match len dist)
  | _ => none

/-- ASCII whitespace exactly as Rust's `u8::is_ascii_whitespace`: space,
    tab, LF, FF (U+000C) and CR, but not VT (U+000B). Lean's
    `Char.isWhitespace` misses FF and `String.trimAscii` also strips VT, so
    the oracle uses this one predicate for trimming and splitting. -/
def isAsciiWs (c : Char) : Bool :=
  c = ' ' || c = '\t' || c = '\n' || c = '\x0c' || c = '\r'

/-- Trim `isAsciiWs` from both ends. Rust: `str::trim_ascii`. -/
def trimWs (s : String) : String :=
  String.ofList ((s.toList.dropWhile isAsciiWs).reverse.dropWhile isAsciiWs).reverse

/-- Split on runs of `isAsciiWs`, dropping empty words. Rust:
    `str::split_ascii_whitespace`. -/
def wordsWs (s : String) : List String :=
  (s.split isAsciiWs).toList.map (·.toString) |>.filter (· ≠ "")

/-- `EMIT` body: whitespace-separated tokens, through `emitFixed` alone. -/
def emitAndFormat (body : String) : String :=
  let words := wordsWs body
  match words.mapM parseToken? with
  | none => "ERR badToken"
  | some ts => s!"OK {toHex (emitFixed ts)}"

/-- `EMITBLOCKS` body: tokens through `emitBlocks` with no lengths (fixed
    blocks only, chunks of 16384). Rust: `emit_blocks_fixed_reply`. -/
def emitBlocksAndFormat (body : String) : String :=
  let words := wordsWs body
  match words.mapM parseToken? with
  | none => "ERR badToken"
  | some ts => s!"OK {toHex (emitBlocks (fun _ => none) ts)}"

/-- `EMITDYN` lengths: one hex digit per length, `lo`–`hi` digits.
    Rust: `parse_lengths` in `vdeflate`. -/
def parseLengths? (s : String) (lo hi : Nat) : Option (Array Nat) :=
  if lo ≤ s.length ∧ s.length ≤ hi then (s.toList.mapM hexDigit?).map List.toArray else none

/-- `EMITDYN <lit> <dist> <cl> <tok>*`: one final block, dynamic when
    `validLengths` holds (no size comparison), fixed otherwise. Lengths are
    checked before tokens. Rust: `emit_dyn_reply` in `vdeflate`. -/
def emitDynAndFormat (body : String) : String :=
  let words := wordsWs body
  let lens : Option (Array Nat × Array Nat × Array Nat × List String) :=
    match words with
    | l :: d :: c :: toks => do
      let lit ← parseLengths? l 257 286
      let dist ← parseLengths? d 1 30
      let cl ← parseLengths? c 19 19
      pure (lit, dist, cl, toks)
    | _ => none
  match lens with
  | none => "ERR badLengths"
  | some (lit, dist, cl, toks) =>
    match toks.mapM parseToken? with
    | none => "ERR badToken"
    | some ts =>
      let w := if validLengths lit dist cl ts then emitDynamicBlock BitWriter.empty true lit dist cl ts
        else emitFixedBlock BitWriter.empty true ts
      s!"OK {toHex w.toBytes}"

/-- `DEFLATE` uses the trivial finder and no dynamic lengths, so the model
    emits literals in fixed blocks and `compress` picks between that and
    stored. -/
def deflateAndFormat (hx : String) : String :=
  match ofHex hx with
  | none => "ERR badHex"
  | some bs => s!"OK {toHex (compress (fun _ _ => none) (fun _ => none) bs)}"

/-- Framing byte arguments use `-` for empty, including the ZIP filename. -/
def framingHex (s : String) : Option ByteArray := ofHex (if s = "-" then "" else s)

def framingAndFormat (limit : Nat) (cmd : String) (args : List String) : String :=
  if cmd = "ZIPSTORE" then
    match args with
    | [n, d] => match framingHex n, framingHex d with
      | some name, some input => match NativeZip.zip name input with
        | .ok wire => s!"OK {toHex wire}"
        | .error _ => "ERR fields"
      | _, _ => "ERR badHex"
    | _ => "ERR arguments"
  else
    let hx := match args with | [] => some "-" | [h] => some h | _ => none
    match hx.bind framingHex with
    | none => "ERR badHex"
    | some bs =>
      if cmd = "CRC32" then s!"OK {(NativeCRC32.crc32 bs).toNat}"
      else if cmd = "GZIP" then
        s!"OK {toHex (NativeGzip.gzip (fun _ _ => none) (fun _ => none) bs)}"
      else if cmd = "GUNZIP" then
        match NativeGzip.gunzip bs limit with
        | .ok out => s!"OK {toHex out}"
        | .error _ => "ERR gzip"
      else match NativeZip.unzip bs limit with
        | .ok (name, input) => s!"OK {toHex name} {toHex input}"
        | .error _ => "ERR zip"

def handle (limit : Nat) (line : String) : Nat × Option String :=
  let t := trimWs line
  match wordsWs t with
  | cmd :: args =>
    if cmd = "CRC32" ∨ cmd = "GZIP" ∨ cmd = "GUNZIP" ∨ cmd = "ZIPSTORE" ∨ cmd = "UNZIPSTORE" then
      (limit, some (framingAndFormat limit cmd args))
    else legacyHandle limit t
  | [] => (limit, none)
where
  legacyHandle (limit : Nat) (t : String) : Nat × Option String :=
  -- EMIT takes a token list, so split off only the command word (Rust: `splitn(2, ' ')`).
  match t.splitOn " " with
  | "EMIT" :: _ => (limit, some (emitAndFormat (t.drop 4).toString))
  | "EMITBLOCKS" :: _ => (limit, some (emitBlocksAndFormat (t.drop 10).toString))
  | "EMITDYN" :: _ => (limit, some (emitDynAndFormat (t.drop 7).toString))
  | _ =>
  match (t.splitOn " ") with
  | ["LIMIT", n] => (n.toNat?.getD limit, none)
  | ["DECODE"] => (limit, some (decodeAndFormat limit ""))
  | ["DECODE", hx] => (limit, some (decodeAndFormat limit hx))
  | ["ENCODE"] => (limit, some s!"OK {toHex (Deflate.encodeStored ⟨#[]⟩)}")
  | ["ENCODE", hx] =>
    match ofHex hx with
    | none => (limit, some "ERR badHex")
    | some bs => (limit, some s!"OK {toHex (Deflate.encodeStored bs)}")
  | ["DEFLATE"] => (limit, some (deflateAndFormat ""))
  | ["DEFLATE", hx] => (limit, some (deflateAndFormat hx))
  | _ => (limit, none)

def main (_args : List String) : IO Unit := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let mut limit := 1 <<< 26
  repeat
    let line ← stdin.getLine
    if line.isEmpty then break
    let (lim, out) := handle limit line
    limit := lim
    match out with
    | some s => do
      stdout.putStrLn s
      stdout.flush
    | none => pure ()
