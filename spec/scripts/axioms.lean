-- CI: the headline theorems must rest only on Lean's standard axioms.
-- Run with `lake env lean spec/scripts/axioms.lean`; CI fails on `sorryAx`.
-- Theorem names are added here by the task that proves them.
import Deflate
open Deflate
#print axioms Deflate.accept_prefix
#print axioms Deflate.better_match_iff_threshold
#print axioms Deflate.decodeSymFastAt_eq
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
#print axioms Deflate.fixedLitLen_complete
#print axioms Deflate.fixedDist_complete
#print axioms Deflate.decodeSym_pos
#print axioms Deflate.decodeSym_bytes
#print axioms Deflate.decodeSym_in_range
#print axioms Deflate.decodeSym_local
#print axioms Deflate.decodeSymFast_eq
#print axioms Deflate.buildTable_size
#print axioms Deflate.tableEntry_some
#print axioms Deflate.readBits_some
#print axioms Deflate.fixedLitLen_table_total
#print axioms Deflate.fixedDist_table_total
#print axioms Deflate.copyBack_size
#print axioms Deflate.copyBack_overlap
#print axioms Deflate.copyBack_rejects
#print axioms Deflate.readLength_range
#print axioms Deflate.readDistance_range
#print axioms Deflate.decodeHuffBlock_monotone
#print axioms Deflate.decodeHuffBlock_within_limit
#print axioms Deflate.decodeHuffBlock_progress
#print axioms Deflate.clOrder_is_a_permutation
#print axioms Deflate.readDynamicCodes_valid
#print axioms Deflate.readDynamicCodes_pos
#print axioms Deflate.decode_deterministic
#print axioms Deflate.decode_within_limit
#print axioms Deflate.encodeStored_empty
#print axioms Deflate.encodeStored_valid
#print axioms Deflate.decode_encodeStored
#print axioms Deflate.expand_compressTokens
#print axioms Deflate.compressTokens_valid
#print axioms Deflate.valid_iff_prefix
#print axioms Deflate.toBytes_bitAt
#print axioms Deflate.readBits_written
#print axioms Deflate.agree_written
#print axioms Deflate.agree_patternReader_written
#print axioms Deflate.decodeSym_written
#print axioms Deflate.decodeSym_writeCode
#print axioms Deflate.bitAt_writeCode
#print axioms Deflate.fixedLit_code_decodes
#print axioms Deflate.fixedDist_code_decodes
#print axioms Deflate.lengthSym_reads
#print axioms Deflate.distSym_reads
#print axioms Deflate.decode_emitFixed
#print axioms Deflate.decode_compress
#print axioms Deflate.compress_none
#print axioms Deflate.decodeSym_of_canonical_bits
#print axioms Deflate.decodeSym_canonical
#print axioms Deflate.canonicalCode_fixedLit
#print axioms Deflate.canonicalCode_fixedDist
#print axioms Deflate.rleLengths_expand
#print axioms Deflate.rleLengths_inRange
#print axioms Deflate.readCodeLengths_go_emit
#print axioms Deflate.readCLLens_go_emit
#print axioms Deflate.readDynamicCodes_emitHeader
#print axioms Deflate.validLengths_spec
#print axioms Deflate.huffLoop
#print axioms Deflate.readHeader_written
#print axioms Deflate.decodeBlock_emitFixedBlock
#print axioms Deflate.decodeBlock_emitDynamicBlock
#print axioms Deflate.decodeBlock_emitBlock
#print axioms Deflate.decodeFuelLoop_emitBlocksGo
#print axioms Deflate.decode_emitBlocks
#print axioms Deflate.emitBlocks_none

-- General fuel sufficiency, including malformed input.
#print axioms Deflate.readCodeLengths_go_fuel_sufficient
#print axioms Deflate.readCodeLengths_never_exhausts
#print axioms Deflate.readCLLens_never_exhausts
#print axioms Deflate.readDynamicCodes_never_exhausts
#print axioms Deflate.decodeHuffBlock_fuel_sufficient
#print axioms Deflate.decodeBlockBody_never_exhausts
#print axioms Deflate.decodeFuelLoop_fuel_sufficient
#print axioms Deflate.decode_never_exhausts

-- Checked custom block splitting for every callback and length heuristic.
#print axioms Deflate.checkedSplit_bounds
#print axioms Deflate.splitCount_progress
#print axioms Deflate.splitCount_bounds
#print axioms Deflate.decode_emitSplitBlocks
#print axioms Deflate.decode_compressSplit
#print axioms Deflate.emitSplitBlocks_none

-- Native-byte framing: explicit minimal gzip and canonical STORED ZIP subsets.
#print axioms Deflate.NativeFraming.readLE_le
#print axioms Deflate.NativeCRC32.crc32_check
#print axioms Deflate.NativeCRC32.crc32_empty
#print axioms Deflate.NativeGzip.gunzip_gzip
#print axioms Deflate.NativeGzip.accepted_integrity
#print axioms Deflate.NativeGzip.gunzip_within_limit
#print axioms Deflate.NativeGzip.output_limit_rejection
#print axioms Deflate.NativeGzip.checksum_mismatch_rejection
#print axioms Deflate.NativeZip.zip_rejects_fields
#print axioms Deflate.NativeZip.unzip_zip
#print axioms Deflate.NativeZip.accepted_integrity
#print axioms Deflate.NativeZip.unzip_within_limit
#print axioms Deflate.NativeZip.output_limit_rejection
#print axioms Deflate.NativeZip.checksum_mismatch_rejection
