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

/-- Until Task 18 provides `Deflate.decode`, drive blocks here directly. -/
partial def decodeStored (bs : ByteArray) (limit : Nat) :
    Except DecErr ByteArray := do
  let rec loop (r : BitReader) (out : Array UInt8) : Except DecErr ByteArray := do
    let (h, r₁) ← readHeader r
    match h.btype with
    | .stored =>
        let (out', r₂) ← readStored r₁ out
        if out'.size > limit then .error .outputLimitExceeded
        else if h.isFinal then .ok ⟨out'⟩ else loop r₂ out'
    | .fixed =>
        let (out', r₂) ← decodeHuffBlock fixedLitLen fixedDist r₁ out limit (8 * bs.size + 1)
        if h.isFinal then .ok ⟨out'⟩ else loop r₂ out'
    | .dynamic =>
        let ((lit, dst), r₂) ← readDynamicCodes r₁
        let (out', r₃) ← decodeHuffBlock lit dst r₂ out limit (8 * bs.size + 1)
        if h.isFinal then .ok ⟨out'⟩ else loop r₃ out'
  loop ⟨bs, 0⟩ #[]

def decodeAndFormat (limit : Nat) (hx : String) : String :=
  match ofHex hx with
  | none => "ERR badHex"
  | some bs =>
    match decodeStored bs limit with
    | .ok out => s!"OK {toHex out}"
    | .error e => s!"ERR {errName e}"

def handle (limit : Nat) (line : String) : Nat × Option String :=
  match (line.trimAscii.toString.splitOn " ") with
  | ["LIMIT", n] => (n.toNat?.getD limit, none)
  | ["DECODE"] => (limit, some (decodeAndFormat limit ""))
  | ["DECODE", hx] => (limit, some (decodeAndFormat limit hx))
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
