import Deflate.Properties

/-! Native-byte framing helpers. Slices are total; container decoders separately
check lengths or equality with a complete canonical encoding. -/
namespace Deflate.NativeFraming

def bytes (xs : List UInt8) : ByteArray := ⟨xs.toArray⟩
def octets (x : ByteArray) : List UInt8 := x.data.toList

@[simp] theorem octets_bytes (xs : List UInt8) : octets (bytes xs) = xs := by
  simp [octets, bytes]
@[simp] theorem bytes_octets (x : ByteArray) : bytes (octets x) = x := by
  cases x; simp [octets, bytes]
@[simp] theorem length_octets (x : ByteArray) : (octets x).length = x.size := by
  rfl
@[simp] theorem size_bytes (xs : List UInt8) : (bytes xs).size = xs.length := by
  exact List.size_toArray

/-- Little endian, truncating to exactly `width` octets. -/
def le : Nat → Nat → List UInt8
  | 0, _ => []
  | k + 1, n => UInt8.ofNat n :: le k (n / 256)

def readLE : List UInt8 → Nat
  | [] => 0
  | b :: bs => b.toNat + 256 * readLE bs

@[simp] theorem length_le (k n : Nat) : (le k n).length = k := by
  induction k generalizing n <;> simp [le, *]

theorem readLE_le (k n : Nat) (h : n < 256 ^ k) : readLE (le k n) = n := by
  induction k generalizing n with
  | zero =>
    simp only [Nat.pow_zero] at h
    have hn : n = 0 := by omega
    simp [hn, le, readLE]
  | succ k ih =>
    have hd : n / 256 < 256 ^ k := by
      apply (Nat.div_lt_iff_lt_mul (by decide : 0 < 256)).2
      simpa [Nat.pow_succ] using h
    simp only [le, readLE, UInt8.toNat_ofNat', ih _ hd]
    omega

/-- Slice by offset and length. -/
def slice (xs : List UInt8) (off len : Nat) : List UInt8 := (xs.drop off).take len

theorem slice_middle (a b c : List UInt8) :
    slice (a ++ b ++ c) a.length b.length = b := by
  simp [slice, List.append_assoc]

end Deflate.NativeFraming
