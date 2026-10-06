import Deflate.Framing

/-! Reflected CRC-32/ISO-HDLC used by RFC 1952 and ZIP. This computes a
checksum, with no assumption of collision freedom or universal error detection. -/
namespace Deflate.NativeCRC32

def bitStep (c : UInt32) : UInt32 :=
  if c &&& 1 == 1 then (c >>> 1) ^^^ 0xEDB88320 else c >>> 1

def bits : Nat → UInt32 → UInt32
  | 0, c => c
  | n + 1, c => bits n (bitStep c)

def byteStep (c : UInt32) (b : UInt8) : UInt32 :=
  bits 8 (c ^^^ UInt32.ofNat b.toNat)

def crc32 (input : ByteArray) : UInt32 :=
  (NativeFraming.octets input).foldl byteStep 0xFFFFFFFF ^^^ 0xFFFFFFFF

set_option maxRecDepth 10000 in
set_option maxHeartbeats 2000000 in
/-- Standard check vector, evaluated by the kernel. -/
theorem crc32_check :
    crc32 (NativeFraming.bytes [49,50,51,52,53,54,55,56,57]) = 0xCBF43926 := by
  decide

theorem crc32_empty : crc32 (NativeFraming.bytes []) = 0 := by decide

end Deflate.NativeCRC32
