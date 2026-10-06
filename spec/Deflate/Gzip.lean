import Deflate.CRC32

/-! Canonical minimal-header gzip with one decoded DEFLATE body and a checked
CRC32/ISIZE trailer. Optional headers and concatenated-member decoding are not
modeled. The body uses the existing raw decoder, including its tolerance of
unused trailing body bytes; no exact compressed-input-consumption claim is made.
Model boundary: crates/deflate-core/{src/gzip.rs,tests/gzip_review_tests.rs};
this is an executable format model, not a Rust refinement proof. -/
namespace Deflate.NativeGzip
open NativeFraming NativeCRC32

/-- ID1 ID2 CM FLG MTIME XFL OS (unknown OS). -/
def header : List UInt8 := [0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 255]
def trailer (input : ByteArray) : List UInt8 :=
  le 4 (crc32 input).toNat ++ le 4 (input.size % 4294967296)

def gzip (find : Finder) (lf : LengthsFor) (input : ByteArray) : ByteArray :=
  bytes (header ++ octets (compress find lf input) ++ trailer input)

def body (wire : ByteArray) : ByteArray := bytes (slice (octets wire) 10 (wire.size - 18))
def tailBytes (wire : ByteArray) : List UInt8 := (octets wire).drop (wire.size - 8)

inductive Error where
  | header | deflate | integrity
  deriving DecidableEq, Repr

def gunzip (wire : ByteArray) (limit : Nat) : Except Error ByteArray :=
  if wire.size < 18 ∨ (octets wire).take 10 ≠ header then .error .header
  else match decode (body wire) limit with
    | .error _ => .error .deflate
    | .ok out => if tailBytes wire = trailer out then .ok out else .error .integrity

@[simp] theorem length_header : header.length = 10 := rfl
@[simp] theorem length_trailer (x : ByteArray) : (trailer x).length = 8 := by
  simp [trailer]

private theorem encoded_parts (find : Finder) (lf : LengthsFor) (x : ByteArray) :
    ¬ ((gzip find lf x).size < 18 ∨ (octets (gzip find lf x)).take 10 ≠ header) ∧
    body (gzip find lf x) = compress find lf x ∧
    tailBytes (gzip find lf x) = trailer x := by
  have hs : (gzip find lf x).size = 10 + (compress find lf x).size + 8 := by
    simp [gzip, Nat.add_assoc]
  have hh : (octets (gzip find lf x)).take 10 = header := by
    simp only [gzip, octets_bytes, List.append_assoc]
    simpa only [length_header] using (List.take_left (l₁ := header) (l₂ := octets (compress find lf x) ++ trailer x))
  have hb : body (gzip find lf x) = compress find lf x := by
    unfold body
    rw [hs]
    have hn : 10 + (compress find lf x).size + 8 - 18 = (compress find lf x).size := by omega
    rw [hn]
    simp only [gzip, octets_bytes]
    rw [← length_header, ← length_octets (compress find lf x), slice_middle, bytes_octets]
  have ht : tailBytes (gzip find lf x) = trailer x := by
    unfold tailBytes
    rw [hs]
    simp only [gzip, octets_bytes, Nat.add_sub_cancel]
    have hl : (header ++ octets (compress find lf x)).length = 10 + (compress find lf x).size := by simp
    rw [← hl, List.drop_left]
  exact ⟨by simp [hs, hh], hb, ht⟩

/-- Arbitrary finder and length proposal function; only the output limit is assumed. -/
theorem gunzip_gzip (find : Finder) (lf : LengthsFor) (input : ByteArray)
    (limit : Nat) (h : input.size ≤ limit) :
    gunzip (gzip find lf input) limit = .ok input := by
  obtain ⟨hh, hb, ht⟩ := encoded_parts find lf input
  simp [gunzip, hh, hb, ht, decode_compress find lf input limit h]

/-- Acceptance checks the header, actual decoded body, CRC32 and size trailer. -/
theorem accepted_integrity {wire out : ByteArray} {limit : Nat}
    (h : gunzip wire limit = .ok out) :
    18 ≤ wire.size ∧ (octets wire).take 10 = header ∧
    decode (body wire) limit = .ok out ∧ tailBytes wire = trailer out := by
  unfold gunzip at h
  split at h
  · contradiction
  · rename_i hh
    simp only [not_or, Nat.not_lt, ne_eq, Decidable.not_not] at hh
    split at h
    · contradiction
    · rename_i decoded hd
      split at h
      · cases h; exact ⟨hh.1, hh.2, hd, by assumption⟩
      · contradiction

theorem gunzip_within_limit {wire out : ByteArray} {limit : Nat}
    (h : gunzip wire limit = .ok out) : out.size ≤ limit :=
  decode_within_limit (accepted_integrity h).2.2.1

theorem output_limit_rejection {wire out : ByteArray} {limit : Nat}
    (h : limit < out.size) : gunzip wire limit ≠ .ok out := by
  intro ok; have := gunzip_within_limit ok; omega

/-- A mismatching CRC field cannot be accepted as this output. No claim about
CRC collisions or about every possible corruption is made. -/
theorem checksum_mismatch_rejection {wire out : ByteArray} {limit : Nat}
    (h : (tailBytes wire).take 4 ≠ le 4 (crc32 out).toNat) :
    gunzip wire limit ≠ .ok out := by
  intro ok
  apply h
  rw [(accepted_integrity ok).2.2.2]
  simp only [trailer]
  simpa only [length_le] using (List.take_left (l₁ := le 4 (crc32 out).toNat) (l₂ := le 4 (out.size % 4294967296)))

end Deflate.NativeGzip
