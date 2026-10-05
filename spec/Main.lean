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

def handle (limit : Nat) (line : String) : Nat × Option String :=
  match (line.trimAscii.toString.splitOn " ") with
  | ["LIMIT", n] => (n.toNat?.getD limit, none)
  | ["DECODE"] => (limit, some (decodeAndFormat limit ""))
  | ["DECODE", hx] => (limit, some (decodeAndFormat limit hx))
  | ["ENCODE"] => (limit, some s!"OK {toHex (Deflate.encodeStored ⟨#[]⟩)}")
  | ["ENCODE", hx] =>
    match ofHex hx with
    | none => (limit, some "ERR badHex")
    | some bs => (limit, some s!"OK {toHex (Deflate.encodeStored bs)}")
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
