import Deflate.CRC32

/-! Strict canonical single-entry STORED ZIP (PKWARE APPNOTE 4.3.7/12/16).
Actual local header, central directory and EOCD bytes; raw filename bytes;
no extra fields, comments, descriptors, encryption, multiple entries, DEFLATE
or ZIP64. DOS date/time and flags are zero; version needed is 2.0, made-by is 4.5.
The decoder extracts fields from bytes and rebuilds the whole container to
validate all metadata and the actual payload CRC. Model boundary:
crates/deflate-core/{src/zip.rs,tests/zip_review_tests.rs}, not Rust refinement. -/
namespace Deflate.NativeZip
open NativeFraming NativeCRC32

/-- Every variable-width field must fit, including the central directory offset.
The all-ones 32-bit size/offset ZIP64 sentinel is excluded, matching `zip_single`.
The filename bound also ensures the central directory length (46 + name.size) fits. -/
def ValidFields (name input : ByteArray) : Prop :=
  name.size < 65536 ∧ input.size < 4294967295 ∧
  30 + name.size + input.size < 4294967295
instance (name input : ByteArray) : Decidable (ValidFields name input) :=
  inferInstanceAs (Decidable (_ ∧ _ ∧ _))

/-- Signature, version, flags, STORED method, DOS time/date. -/
def localPrefix : List UInt8 := [80,75,3,4,20,0,0,0,0,0,0,0,0,0]
def localHeader (name input : ByteArray) : List UInt8 :=
  localPrefix ++ le 4 (crc32 input).toNat ++ le 4 input.size ++
  le 4 input.size ++ le 2 name.size ++ [0,0]

def central (name input : ByteArray) : List UInt8 :=
  [80,75,1,2,45,0,20,0,0,0,0,0,0,0,0,0] ++
  le 4 (crc32 input).toNat ++ le 4 input.size ++ le 4 input.size ++
  le 2 name.size ++ [0,0,0,0,0,0,0,0] ++ le 4 0 ++ le 4 0 ++ octets name

def eocd (name input : ByteArray) : List UInt8 :=
  [80,75,5,6,0,0,0,0,1,0,1,0] ++ le 4 (46 + name.size) ++
  le 4 (30 + name.size + input.size) ++ [0,0]

/-- Byte construction; `zip` is the checked public encoder. -/
def canonical (name input : ByteArray) : ByteArray :=
  bytes (localHeader name input ++ octets name ++ octets input ++
    central name input ++ eocd name input)

inductive Error where
  | fields | limit | container
  deriving DecidableEq, Repr

def zip (name input : ByteArray) : Except Error ByteArray :=
  if ValidFields name input then .ok (canonical name input) else .error .fields

/-- Parsed from the local header, never externally supplied. -/
def nameLength (wire : ByteArray) : Nat := readLE (slice (octets wire) 26 2)
def storedSize (wire : ByteArray) : Nat := readLE (slice (octets wire) 18 4)
def parsedName (wire : ByteArray) : ByteArray := bytes (slice (octets wire) 30 (nameLength wire))
def parsedData (wire : ByteArray) : ByteArray :=
  bytes (slice (octets wire) (30 + nameLength wire) (storedSize wire))

def unzip (wire : ByteArray) (limit : Nat) : Except Error (ByteArray × ByteArray) :=
  if storedSize wire > limit then .error .limit
  else
    let name := parsedName wire
    let input := parsedData wire
    if ValidFields name input ∧ wire = canonical name input then .ok (name, input)
    else .error .container

@[simp] theorem length_localPrefix : localPrefix.length = 14 := rfl
@[simp] theorem length_localHeader (name input : ByteArray) :
    (localHeader name input).length = 30 := by simp [localHeader]
@[simp] theorem length_central (name input : ByteArray) :
    (central name input).length = 46 + name.size := by simp [central]; omega
@[simp] theorem length_eocd (name input : ByteArray) :
    (eocd name input).length = 22 := by simp [eocd]

theorem size_canonical (name input : ByteArray) :
    (canonical name input).size = 98 + 2 * name.size + input.size := by
  simp [canonical]; omega

private theorem local_name_field (name input : ByteArray) :
    slice (octets (canonical name input)) 26 2 = le 2 name.size := by
  simp [canonical, slice, localHeader, List.drop_append,
    List.drop_eq_nil_of_le]

private theorem local_size_field (name input : ByteArray) :
    slice (octets (canonical name input)) 18 4 = le 4 input.size := by
  simp [canonical, slice, localHeader, List.drop_append, List.take_append]

private theorem parsed_canonical (name input : ByteArray) (h : ValidFields name input) :
    nameLength (canonical name input) = name.size ∧
    storedSize (canonical name input) = input.size ∧
    parsedName (canonical name input) = name ∧
    parsedData (canonical name input) = input := by
  have hn : nameLength (canonical name input) = name.size := by
    rw [nameLength, local_name_field]
    exact readLE_le 2 name.size h.1
  have hs : storedSize (canonical name input) = input.size := by
    rw [storedSize, local_size_field]
    exact readLE_le 4 input.size (by have := h.2.1; omega)
  refine ⟨hn, hs, ?_, ?_⟩
  · unfold parsedName
    rw [hn]
    simp only [canonical, octets_bytes, List.append_assoc]
    have he := slice_middle (localHeader name input) (octets name)
      (octets input ++ central name input ++ eocd name input)
    simp only [length_localHeader, length_octets, List.append_assoc] at he
    rw [he, bytes_octets]
  · unfold parsedData
    rw [hn, hs]
    simp only [canonical, octets_bytes]
    have he := slice_middle (localHeader name input ++ octets name) (octets input)
      (central name input ++ eocd name input)
    simp only [List.length_append, length_localHeader, length_octets] at he
    rw [List.append_assoc (localHeader name input ++ octets name ++ octets input), he,
      bytes_octets]

/-- The encoder rejects field overflow rather than silently truncating it. -/
theorem zip_rejects_fields {name input : ByteArray} (h : ¬ ValidFields name input) :
    zip name input = .error .fields := by simp [zip, h]

/-- General round trip through the checked executable encoder and decoder. -/
theorem unzip_zip (name input : ByteArray) (limit : Nat)
    (hf : ValidFields name input) (hl : input.size ≤ limit) :
    (zip name input).bind (fun wire => unzip wire limit) = .ok (name, input) := by
  obtain ⟨hn, hs, hp, hd⟩ := parsed_canonical name input hf
  simp [zip, hf, unzip, hs, hp, hd, Nat.not_lt.mpr hl, Except.bind]

/-- Acceptance implies exact canonical bytes, including CRC, both size fields,
central metadata and EOCD; it also implies the output limit. -/
theorem accepted_integrity {wire name input : ByteArray} {limit : Nat}
    (h : unzip wire limit = .ok (name, input)) :
    ValidFields name input ∧ wire = canonical name input ∧ input.size ≤ limit := by
  unfold unzip at h
  split at h
  · contradiction
  · rename_i hl
    dsimp only at h
    split at h
    · rename_i hc
      have hp : parsedName wire = name ∧ parsedData wire = input := by
        simpa only [Except.ok.injEq, Prod.mk.injEq] using h
      rw [hp.1, hp.2] at hc
      refine ⟨hc.1, hc.2, ?_⟩
      have hs := (parsed_canonical name input hc.1).2.1
      rw [← hc.2] at hs
      omega
    · contradiction

theorem unzip_within_limit {wire name input : ByteArray} {limit : Nat}
    (h : unzip wire limit = .ok (name, input)) : input.size ≤ limit :=
  (accepted_integrity h).2.2

theorem output_limit_rejection {wire name input : ByteArray} {limit : Nat}
    (h : limit < input.size) : unzip wire limit ≠ .ok (name, input) := by
  intro ok; have := unzip_within_limit ok; omega

/-- The local CRC field is at byte offset 14; the whole-container equality also
checks its central directory copy. This is checksum validation, not collision freedom. -/
theorem checksum_mismatch_rejection {wire name input : ByteArray} {limit : Nat}
    (h : slice (octets wire) 14 4 ≠ le 4 (crc32 input).toNat) :
    unzip wire limit ≠ .ok (name, input) := by
  intro ok
  apply h
  rw [(accepted_integrity ok).2.1]
  simp [canonical, slice, localHeader]

end Deflate.NativeZip
