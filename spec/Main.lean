import Deflate

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

/-- `EMIT` body: whitespace-separated tokens, through `emitFixed` alone. -/
def emitAndFormat (body : String) : String :=
  let words := (body.split Char.isWhitespace).toList.map (·.toString) |>.filter (· ≠ "")
  match words.mapM parseToken? with
  | none => "ERR badToken"
  | some ts => s!"OK {toHex (emitFixed ts)}"

/-- `DEFLATE` uses the trivial finder, so the model emits only literals and
    `compress` picks between that and stored. -/
def deflateAndFormat (hx : String) : String :=
  match ofHex hx with
  | none => "ERR badHex"
  | some bs => s!"OK {toHex (compress (fun _ _ => none) bs)}"

def handle (limit : Nat) (line : String) : Nat × Option String :=
  let t := line.trimAscii.toString
  -- EMIT takes a token list, so split off only the command word (Rust: `splitn(2, ' ')`).
  match t.splitOn " " with
  | "EMIT" :: _ => (limit, some (emitAndFormat (t.drop 4).toString))
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
  let mut limit := 1 <<< 26
  repeat
    let line ← stdin.getLine
    if line.isEmpty then break
    let (lim, out) := handle limit line
    limit := lim
    match out with
    | some s => IO.println s
    | none => pure ()
