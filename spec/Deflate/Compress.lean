/-
  Deflate.Compress — the model compressor (spec §3.6).

  Tokenize with the untrusted finder, emit one fixed-Huffman block, and keep
  it only if it is strictly smaller than the stored encoding. Ties go to
  stored, which decodes faster. `Properties.decode_compress` is the round
  trip. Rust counterpart: `deflate` in `deflate-core`.
-/
import Deflate.Match
import Deflate.Encode
import Deflate.EncodeFixed

namespace Deflate

/-- The smaller of the fixed-Huffman and stored encodings of `x`. -/
def compress (find : Finder) (x : ByteArray) : ByteArray :=
  let f := emitFixed (compressTokens find x.data)
  let s := encodeStored x
  if f.size < s.size then f else s

end Deflate
