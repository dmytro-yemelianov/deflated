/-
  Deflate.Encode — the minimal encoder (spec §17 M6).

  Stored blocks only. Correctness before ratio (spec §17 M7): this produces a
  valid RFC 1951 stream that is slightly *larger* than its input, which is
  exactly what a stored-block encoder is for. LZ77 and Huffman encoding are a
  later plan.

  A stored block carries at most 65535 bytes, so input is chunked. Empty input
  still produces one block, with BFINAL set and LEN = 0: a stream with no
  blocks at all is not valid DEFLATE.
-/
import Deflate.Decode

namespace Deflate

/-- Maximum payload of one stored block (RFC 1951 §3.2.4: LEN is 16 bits). -/
def maxStored : Nat := 65535

/-- One stored block: the three header bits padded to a byte, LEN and NLEN
    little-endian, then the payload. -/
def encodeBlock (isFinal : Bool) (payload : Array UInt8) : Array UInt8 :=
  let hdr : UInt8 := if isFinal then 1 else 0   -- BFINAL in bit 0, BTYPE = 00
  let n := payload.size
  #[hdr,
    UInt8.ofNat (n % 256), UInt8.ofNat (n / 256),
    UInt8.ofNat ((65535 - n) % 256), UInt8.ofNat ((65535 - n) / 256)] ++ payload

/-- Chunk the input into stored blocks, marking the last one final. Empty
    input yields one empty final block. -/
def encodeStored (bs : ByteArray) : ByteArray :=
  if bs.size ≤ maxStored then
    ⟨encodeBlock true bs.data⟩
  else
    let rec go (rest : Array UInt8) (acc : Array UInt8) : Array UInt8 :=
      if rest.size ≤ maxStored then
        acc ++ encodeBlock true rest
      else
        go (rest.extract maxStored rest.size)
           (acc ++ encodeBlock false (rest.extract 0 maxStored))
      termination_by rest.size
      decreasing_by simp [Array.size_extract, maxStored]; omega
    ⟨go bs.data #[]⟩

end Deflate
