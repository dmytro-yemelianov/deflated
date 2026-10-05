-- CI: the headline theorems must rest only on Lean's standard axioms.
-- Run with `lake env lean spec/scripts/axioms.lean`; CI fails on `sorryAx`.
-- Theorem names are added here by the task that proves them.
import Deflate
open Deflate
#print axioms Deflate.byteAt_oob
#print axioms Deflate.readBits_pos
#print axioms Deflate.readBits_bytes
#print axioms Deflate.readBits_lt
#print axioms Deflate.readBits_eof
#print axioms Deflate.alignToByte_idem
#print axioms Deflate.readHeader_pos
#print axioms Deflate.readStored_aligned
#print axioms Deflate.readStored_consumes
#print axioms Deflate.readStored_rejects_bad_nlen
#print axioms Deflate.fixedLitLen_valid
#print axioms Deflate.fixedDist_valid
#print axioms Deflate.decodeSym_pos
#print axioms Deflate.decodeSym_bytes
#print axioms Deflate.decodeSym_in_range
#print axioms Deflate.copyBack_size
#print axioms Deflate.copyBack_overlap
#print axioms Deflate.copyBack_rejects
#print axioms Deflate.readLength_range
#print axioms Deflate.readDistance_range
#print axioms Deflate.decodeHuffBlock_monotone
#print axioms Deflate.decodeHuffBlock_within_limit
#print axioms Deflate.decodeHuffBlock_progress
