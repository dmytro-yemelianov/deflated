/-
  Deflate.Compress — the model compressor (spec M7a §3.6, M7b §3.5).

  Tokenize with the untrusted finder, emit the token blocks with
  `emitBlocks` (each block dynamic when the untrusted `lengthsFor` gives
  valid, smaller lengths, fixed otherwise), and keep the result only if it
  is strictly smaller than the stored encoding. Ties go to stored, which
  decodes faster. `Properties.decode_compress` is the round trip for every
  finder and every `lengthsFor`. M7a's compressor is the special case
  `lengthsFor := fun _ => none` (`Properties.compress_none`).
  Rust counterpart: `deflate` in `deflate-core`.
-/
import Deflate.Match
import Deflate.Encode
import Deflate.EncodeFixed
import Deflate.EncodeDynamic

namespace Deflate

/-- The smaller of the block encoding and the stored encoding of `x`. -/
def compress (find : Finder) (lengthsFor : LengthsFor) (x : ByteArray) : ByteArray :=
  let b := emitBlocks lengthsFor (compressTokens find x.data)
  let s := encodeStored x
  if b.size < s.size then b else s

end Deflate
