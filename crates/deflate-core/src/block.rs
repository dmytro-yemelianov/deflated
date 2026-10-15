//! Block headers (RFC 1951 §3.2.3) and stored blocks (§3.2.4).
//! Mirrors `spec/Deflate/Block.lean`.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BlockType {
    Stored,
    Fixed,
    Dynamic,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BlockHeader {
    pub is_final: bool,
    pub btype: BlockType,
}

pub fn read_block_header(r: &mut BitReader) -> Result<BlockHeader, Error> {
    let is_final = r.read_bit()? == 1;
    let btype = match r.read_bits(2)? {
        0 => BlockType::Stored,
        1 => BlockType::Fixed,
        2 => BlockType::Dynamic,
        _ => return Err(Error::InvalidBlockType),
    };
    Ok(BlockHeader { is_final, btype })
}

/// Read one stored block into `out`. `budget` is how many more bytes the
/// caller will accept; exceeding it is `OutputLimitExceeded` and nothing is
/// appended. Checking before the copy is what keeps a bomb from allocating.
pub fn read_stored(r: &mut BitReader, out: &mut Vec<u8>, budget: usize) -> Result<(), Error> {
    let len = r.read_aligned_u16_le()? as usize;
    let nlen = r.read_aligned_u16_le()? as usize;
    if nlen != 0xFFFF - len {
        return Err(Error::InvalidStoredLength);
    }
    if len > budget {
        return Err(Error::OutputLimitExceeded);
    }
    // A stored block usually has more stored blocks after it, so make room
    // for the rest of the input at once rather than doubling up to it: that
    // growth was most of the stored-block time (docs/perf-report.md). Capped
    // by the input already in memory and by `budget`, so a bomb cannot use
    // this to allocate (spec §11). Only grows, never shrinks capacity.
    if out.capacity() - out.len() < len {
        out.reserve(r.remaining_bytes().min(budget));
    }
    r.read_aligned_into(out, len)
}

use crate::decode_table::{
    CodeTable, DistTable, END, LITERAL, LitTable, PackedTable, TokenTable, is_subtable, match_value,
};
use crate::huffman::{HuffmanTable, TABLE_BITS};
use crate::lz77::{
    DIST_BASE, DIST_EXTRA, LENGTH_BASE, LENGTH_EXTRA, copy_back, read_distance, read_length,
};

/// Decode one Huffman-coded block body. Serves both fixed and dynamic
/// blocks; they differ only in where `lit` and `dist` come from.
/// `limit` is the absolute ceiling on `out.len()`, checked *before* each
/// append, so a bomb never allocates past it.
/// Mirrors `spec/Deflate/Block.lean`'s `decodeHuffBlock`. Bulk tokens consult
/// the same symbol tables as `decode_fast`; misses and short input fall back
/// to that decoder. Lean proves symbol-table equivalence (`decodeSymFast_eq`),
/// while Rust token composition, cursor and error equivalence are tested.
pub fn decode_huff_block(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    const TABLE_MASK: u64 = (1 << TABLE_BITS) - 1;
    let lit_table = lit.fast_table();
    let dist_table = dist.fast_table();
    let mut buffered = 0u64;
    let mut available = 0usize;
    loop {
        // Reuse lookahead across tokens. `buffered` starts at the reader's
        // logical position; `available` counts only known real input bits.
        // With TABLE_BITS=12, a match needs at most 12+5+12+13 = 42 bits;
        // a successful peek_word supplies at least 57, even when unaligned.
        // Refill before attempting a token that could exhaust this window.
        if available < 42 {
            if let Some(word) = r.peek_word() {
                buffered = word;
                available = 57;
            }
        }
        if available >= 42 {
            let word = buffered;
            let entry = lit_table[(word & TABLE_MASK) as usize];
            let sym = entry >> 4;
            if entry != 0 {
                let bits = usize::from(entry & 15);
                if sym < 256 {
                    r.skip_bits(bits);
                    buffered >>= bits;
                    available -= bits;
                    if out.len() >= limit {
                        return Err(Error::OutputLimitExceeded);
                    }
                    out.push(sym as u8);
                    continue;
                }
                if sym == 256 {
                    r.skip_bits(bits);
                    return Ok(());
                }
                if sym <= 285 {
                    let index = usize::from(sym - 257);
                    let extra = usize::from(LENGTH_EXTRA[index]);
                    let len = usize::from(LENGTH_BASE[index])
                        + ((word >> bits) & ((1 << extra) - 1)) as usize;
                    let bits = bits + extra;
                    let distance = dist_table[((word >> bits) & TABLE_MASK) as usize];
                    let dsym = usize::from(distance >> 4);
                    if distance != 0 && dsym < DIST_BASE.len() {
                        let bits = bits + usize::from(distance & 15);
                        let extra = usize::from(DIST_EXTRA[dsym]);
                        let d = usize::from(DIST_BASE[dsym])
                            + ((word >> bits) & ((1 << extra) - 1)) as usize;
                        r.skip_bits(bits + extra);
                        buffered >>= bits + extra;
                        available -= bits + extra;
                        if out.len().saturating_add(len) > limit {
                            return Err(Error::OutputLimitExceeded);
                        }
                        copy_back(out, d, len)?;
                        continue;
                    }
                }
            }
        }
        // A miss/reserved symbol/short window consumes nothing speculatively.
        // The scalar decoder determines the exact error and cursor. Discard
        // cached bits because that decoder can advance by a variable amount.
        available = 0;
        let sym = lit.decode_fast(r)?;
        if sym < 256 {
            if out.len() >= limit {
                return Err(Error::OutputLimitExceeded);
            }
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let len = read_length(sym, r)?;
            let dsym = dist.decode_fast(r)?;
            let d = read_distance(dsym, r)?;
            if out.len().saturating_add(len) > limit {
                return Err(Error::OutputLimitExceeded);
            }
            copy_back(out, d, len)?;
        }
        // No explicit fuel: `lit.decode_fast` consumes at least one bit on every
        // path that returns `Ok`, and the stream is finite, so the loop
        // terminates with `UnexpectedEof` if nothing else stops it first.
        // `spec/Deflate/Properties.lean`'s `decodeHuffBlock_progress` is the
        // model's statement of that argument.
    }
}

#[inline(always)]
pub(crate) fn decode_tokens<L: TokenTable, D: TokenTable>(
    lit: &L,
    dist: &D,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    // Initialize only a bounded region, never exceeding the caller's limit.
    // Spare Vec capacity is not readable/writable initialized slice storage.
    const CHUNK: usize = 8192;
    while limit.saturating_sub(out.len()) >= 264 && r.byte_window().len() >= 64 {
        let mut cursor = out.len();
        let end = cursor + limit.saturating_sub(cursor).min(CHUNK);
        out.resize(end, 0);
        loop {
            let (written, consumed, ended) =
                decode_batch(lit, dist, r.byte_window(), r.bit_pos() % 8, out, cursor);
            cursor = written;
            r.skip_bits(consumed);
            if ended {
                out.truncate(cursor);
                return Ok(());
            }
            if end - cursor < 264 || r.byte_window().len() < 8 {
                break;
            }
            // A table miss uses the same initialized region. Avoid repeatedly
            // clearing a large tail, or abandoning batching for a whole block,
            // when a rare long code occurs between otherwise fast tokens.
            match decode_slice_token(lit, dist, r, out, &mut cursor) {
                Ok(false) => {}
                result => {
                    out.truncate(cursor);
                    return result.map(|_| ());
                }
            }
        }
        out.truncate(cursor);
    }
    decode_huff_tail(lit, dist, r, out, limit)
}

// All writes are inside initialized `out`. At most thirty-seven bytes beyond
// a match are copied; those bytes never enter history until subsequent tokens
// write them. No token is committed on a miss, invalid distance or short input.
#[inline(always)]
fn decode_batch<L: TokenTable, D: TokenTable>(
    lit: &L,
    dist: &D,
    input: &[u8],
    offset: usize,
    out: &mut [u8],
    mut cursor: usize,
) -> (usize, usize, bool) {
    // Every token is bounded by one refill: a match uses at most
    // L::MAX_BITS + 5 + D::BITS + 13 bits and a literal group one resolved
    // code plus two root codes. The next root lookup then still has
    // L::BITS valid bits.
    const {
        assert!(L::MAX_BITS + 5 + D::BITS + 13 <= 56 - L::BITS);
        assert!(L::MAX_BITS + 2 * L::BITS <= 56 - L::BITS);
    };
    let Some(bytes) = input.first_chunk::<8>() else {
        return (cursor, 0, false);
    };
    // Claim only the first seven bytes so `available` stays below 64 and
    // the unconditional refill shift is always in range.
    let mut next = 7;
    let mut word = u64::from_le_bytes(*bytes) >> offset;
    let mut available = 56 - offset;
    let mut entry = lit.lookup(word);
    // Hoisting the input bound leaves the refill without a data-dependent
    // branch. Each iteration consumes fewer bits than one refill supplies.
    let last = input.len().saturating_sub(8);
    while cursor <= out.len() - 264 && next <= last {
        // The logical bit position is next * 8 - available. Refill whole
        // bytes without changing that position, retaining 56..63 bits.
        // Bits above `available` may overlap the next load; they come from
        // those same real input bytes, so OR preserves their values. The
        // preloaded entry used at least L::BITS valid bits and is unchanged.
        let bytes: &[u8; 8] = input[next..][..8].try_into().unwrap();
        word |= u64::from_le_bytes(*bytes) << available;
        next += (63 - available) / 8;
        available |= 56;
        if entry == 0 {
            break;
        }
        let mut bits = (entry & 31) as usize;
        if entry & LITERAL != 0 {
            // The token guard also covers three maximum-width literal codes.
            // One short output slice makes all three stores visibly bounded.
            for byte in &mut out[cursor..][..3] {
                *byte = (entry >> 16) as u8;
                cursor += 1;
                let bits = (entry & 31) as usize;
                available -= bits;
                word >>= bits;
                entry = lit.lookup(word);
                if entry & LITERAL == 0 {
                    break;
                }
            }
            continue;
        } else if entry & END != 0 {
            if L::MAX_BITS > L::BITS && is_subtable(entry) {
                // A refill just supplied at least 56 bits >= L::MAX_BITS.
                // The resolved action is dispatched without consuming input.
                entry = lit.resolve(entry, word);
                if entry == 0 {
                    break;
                }
                continue;
            }
            return (cursor, next * 8 - available + bits - offset, true);
        } else {
            let len = match_value(entry, word);
            let distance_entry = dist.lookup(word >> bits);
            if distance_entry == 0 {
                break;
            }
            let distance = match_value(distance_entry, word >> bits);
            bits += (distance_entry & 31) as usize;
            if distance > cursor {
                break;
            }
            available -= bits;
            word >>= bits;
            // Start the next table load before the independent output copy.
            // This bounded lookup neither reads input nor commits a token.
            entry = lit.lookup(word);
            copy_match(out, cursor, distance, len);
            cursor += len;
            continue;
        }
    }
    (cursor, next * 8 - available - offset, false)
}

// Preconditions are checked by both callers: distance is nonzero and within
// produced history, len <= 258, and at least 264 initialized bytes remain.
#[inline(always)]
fn copy_match(out: &mut [u8], cursor: usize, distance: usize, len: usize) {
    let start = cursor - distance;
    if distance >= 8 {
        // Constant-size safe copies compile to word loads/stores. A
        // distance of at least eight makes each source chunk produced
        // history, including overlapping matches longer than distance.
        // Five unconditional words avoid a copy loop for short matches. Even
        // length three fits the 264-byte guard; padding is not logical history.
        // Express source and destination relative to one checked region so
        // LLVM can prove the five fixed copies are in bounds.
        let area = &mut out[start..][..distance + 264];
        area.copy_within(..8, distance);
        area.copy_within(8..16, distance + 8);
        area.copy_within(16..24, distance + 16);
        area.copy_within(24..32, distance + 24);
        area.copy_within(32..40, distance + 32);
        let mut copied = 40;
        while copied < len {
            area.copy_within(copied..copied + 8, distance + copied);
            copied += 8;
        }
    } else {
        copy_small_distance(out, cursor, distance, len);
    }
}

// Keep variable-size fill/copy calls and their saved loop state off the
// distance >= 8 path. Small distances remain fully supported, not marked cold.
#[inline(never)]
fn copy_small_distance(out: &mut [u8], cursor: usize, distance: usize, len: usize) {
    let start = cursor - distance;
    if distance == 1 {
        let byte = out[start];
        out[cursor..cursor + len].fill(byte);
    } else {
        // Expand an already produced periodic prefix without changing phase.
        let mut copied = 0;
        while copied < len {
            let n = (distance + copied).min(len - copied);
            out.copy_within(start..start + n, cursor + copied);
            copied += n;
        }
    }
}

#[inline]
fn decode_slice_token<L: TokenTable, D: TokenTable>(
    lit: &L,
    dist: &D,
    r: &mut BitReader<'_>,
    out: &mut [u8],
    cursor: &mut usize,
) -> Result<bool, Error> {
    let symbol = lit.decode_symbol(r)?;
    if symbol < 256 {
        out[*cursor] = symbol as u8;
        *cursor += 1;
    } else if symbol == 256 {
        return Ok(true);
    } else {
        let len = read_length(symbol, r)?;
        let distance = read_distance(dist.decode_symbol(r)?, r)?;
        if distance > *cursor {
            return Err(Error::InvalidDistance);
        }
        copy_match(out, *cursor, distance, len);
        *cursor += len;
    }
    Ok(false)
}

#[inline]
fn decode_huff_tail<L: TokenTable, D: TokenTable>(
    lit: &L,
    dist: &D,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    let max_bits = (L::MAX_BITS + 5 + D::BITS + 13) as usize;
    let mut buffered = 0u64;
    let mut available = 0usize;
    loop {
        if available < max_bits {
            if let Some(word) = r.peek_word() {
                buffered = word;
                available = 57;
            }
        }
        if available >= max_bits {
            let word = buffered;
            let entry = lit.lookup_full(word);
            if entry != 0 {
                let bits = (entry & 31) as usize;
                if entry & LITERAL != 0 {
                    r.skip_bits(bits);
                    buffered >>= bits;
                    available -= bits;
                    if out.len() >= limit {
                        return Err(Error::OutputLimitExceeded);
                    }
                    out.push((entry >> 16) as u8);
                    continue;
                }
                if entry & END != 0 {
                    r.skip_bits(bits);
                    return Ok(());
                }
                let len = match_value(entry, word);
                let entry = dist.lookup_full(word >> bits);
                if entry != 0 {
                    let distance = match_value(entry, word >> bits);
                    let bits = bits + (entry & 31) as usize;
                    r.skip_bits(bits);
                    buffered >>= bits;
                    available -= bits;
                    if out.len().saturating_add(len) > limit {
                        return Err(Error::OutputLimitExceeded);
                    }
                    copy_back(out, distance, len)?;
                    continue;
                }
            }
        }
        available = 0;
        let sym = lit.decode_symbol(r)?;
        if sym < 256 {
            if out.len() >= limit {
                return Err(Error::OutputLimitExceeded);
            }
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let len = read_length(sym, r)?;
            let d = read_distance(dist.decode_symbol(r)?, r)?;
            if out.len().saturating_add(len) > limit {
                return Err(Error::OutputLimitExceeded);
            }
            copy_back(out, d, len)?;
        }
    }
}

use crate::huffman::Completeness;

/// RFC 1951 §3.2.7: the order in which code-length code lengths appear.
pub const CL_ORDER: [usize; 19] = [
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

/// Read a dynamic block's two Huffman tables (RFC 1951 §3.2.7).
/// Mirrors `spec/Deflate/Block.lean`'s `readDynamicCodes`.
pub fn read_dynamic_tables(r: &mut BitReader) -> Result<(HuffmanTable, HuffmanTable), Error> {
    let mut cl = None;
    let (lengths, nlen, total) = read_dynamic_lengths(r, &mut cl)?;
    let (lit_lens, dist_lens) = match lengths[..total].split_at_checked(nlen) {
        Some(p) => p,
        None => return Err(Error::InvalidHuffmanTree),
    };
    let lit = HuffmanTable::from_lengths(lit_lens, Completeness::Complete)?;
    // ADR 0004: only the distance tree is allowed to be degenerate.
    let dist = HuffmanTable::from_lengths(dist_lens, Completeness::AllowDegenerate)?;
    Ok((lit, dist))
}

// Owns only working tables, never history or input. Every new header rebuilds
// all three tables, even when the previous stream failed halfway through.
#[derive(Debug, Default)]
pub(crate) struct DynamicTables {
    cl: Option<CodeTable>,
    lit: Option<LitTable>,
    dist: Option<DistTable>,
}

fn update_table<'a, const N: usize, const DIST: bool, const SUB: bool>(
    slot: &'a mut Option<PackedTable<N, DIST, SUB>>,
    lengths: &[u8],
    completeness: Completeness,
) -> Result<&'a PackedTable<N, DIST, SUB>, Error> {
    match slot {
        Some(table) => {
            table.rebuild(lengths, completeness)?;
            Ok(table)
        }
        None => Ok(slot.insert(PackedTable::from_lengths(lengths, completeness)?)),
    }
}

impl DynamicTables {
    pub(crate) fn read(&mut self, r: &mut BitReader) -> Result<(&LitTable, &DistTable), Error> {
        let (lengths, nlen, total) = read_dynamic_lengths(r, &mut self.cl)?;
        let lit = update_table(&mut self.lit, &lengths[..nlen], Completeness::Complete)?;
        let dist = update_table(
            &mut self.dist,
            &lengths[nlen..total],
            Completeness::AllowDegenerate,
        )?;
        Ok((lit, dist))
    }
}

#[inline]
fn read_dynamic_lengths(
    r: &mut BitReader,
    cl: &mut Option<CodeTable>,
) -> Result<([u8; 316], usize, usize), Error> {
    let nlen = r.read_bits(5)? as usize + 257;
    let ndist = r.read_bits(5)? as usize + 1;
    let ncode = r.read_bits(4)? as usize + 4;
    // The 5-bit fields can express more than RFC 1951 permits.
    if nlen > 286 || ndist > 30 {
        return Err(Error::InvalidHuffmanTree);
    }

    let mut cl_lengths = [0u8; 19];
    for &slot in CL_ORDER.iter().take(ncode) {
        let v = r.read_bits(3)? as u8;
        match cl_lengths.get_mut(slot) {
            Some(c) => *c = v,
            None => return Err(Error::InvalidHuffmanTree),
        }
    }
    let cl = update_table(cl, &cl_lengths, Completeness::Complete)?;

    let total = nlen + ndist;
    // The validated header bounds total at 316. Each run writes only its
    // own new region, so zero repeats can leave the initialized bytes alone.
    let mut lengths = [0u8; 286 + 30];
    let mut used = 0;
    while used < total {
        // The table is built anyway; `decodeSymFast_eq` holds for every code.
        let sym = cl.decode_symbol(r)?;
        match sym {
            0..=15 => {
                lengths[used] = sym as u8;
                used += 1;
            }
            16 => {
                let prev = match lengths[..used].last() {
                    Some(p) => *p,
                    None => return Err(Error::InvalidHuffmanTree),
                };
                let n = 3 + r.read_bits(2)? as usize;
                if used + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths[used..used + n].fill(prev);
                used += n;
            }
            17 => {
                let n = 3 + r.read_bits(3)? as usize;
                if used + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                used += n;
            }
            18 => {
                let n = 11 + r.read_bits(7)? as usize;
                if used + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                used += n;
            }
            _ => return Err(Error::InvalidHuffmanTree),
        }
    }

    Ok((lengths, nlen, total))
}

#[cfg(test)]
mod batch_tests {
    use super::*;
    use crate::{bitwriter::BitWriter, decode_table::fixed_tables, tokens::Token};

    #[test]
    fn literal_groups_refill_and_end_at_exact_scalar_positions() {
        let (packed_lit, packed_dist) = fixed_tables();
        let lit = crate::huffman::fixed_litlen();
        let dist = crate::huffman::fixed_dist();
        for offset in 0..8 {
            for count in 0..=70 {
                let mut writer = BitWriter::new();
                writer.write_bits(0, offset);
                let tokens = (0..count).map(|i| Token::Literal((i * 17) as u8));
                crate::encode_fixed::emit_fixed_block(&mut writer, true, tokens);
                let mut bytes = writer.finish();
                let encoded_len = bytes.len();
                bytes.resize(encoded_len + 64, 0xa5);
                for end in (0..=encoded_len).chain([63, 64, 65, bytes.len()]) {
                    for limit in [0, 1, 2, 3, 4, 263, 264, 265, 600] {
                        let mut actual = BitReader::new(&bytes[..end]);
                        let mut reference = BitReader::new(&bytes[..end]);
                        actual.skip_bits(offset as usize + 3);
                        reference.skip_bits(offset as usize + 3);
                        let mut out = Vec::new();
                        let mut expected = Vec::new();
                        let got =
                            decode_tokens(&packed_lit, &packed_dist, &mut actual, &mut out, limit);
                        let want =
                            decode_huff_block(&lit, &dist, &mut reference, &mut expected, limit);
                        assert_eq!(
                            (got, actual.bit_pos(), out),
                            (want, reference.bit_pos(), expected),
                            "offset={offset}, count={count}, end={end}, limit={limit}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn padded_match_copies_equal_bytewise_history_for_all_lengths() {
        for distance in (1..=41).chain([63, 64, 65, 255, 256, 32768]) {
            let history: Vec<u8> = (0..distance).map(|i| (i * 43 + i / 137) as u8).collect();
            for len in 3..=258 {
                let mut expected = history.clone();
                for _ in 0..len {
                    expected.push(expected[expected.len() - distance]);
                }
                let mut actual = history.clone();
                // Nonzero padding makes accidental reads of unwritten history
                // observable; the final sentinel is outside the batch guard.
                actual.resize(distance + 264 + 16, 0xa5);
                copy_match(&mut actual, distance, distance, len);
                assert_eq!(
                    &actual[..distance + len],
                    expected,
                    "distance={distance}, len={len}"
                );
                assert_eq!(&actual[distance + 264..], &[0xa5; 16]);
            }
        }
    }

    #[test]
    fn long_distance_codes_resume_inside_initialized_output() {
        let (packed_lit, _) = fixed_tables();
        let lit = crate::huffman::fixed_litlen();
        let mut lengths = [0; 30];
        for (i, length) in lengths.iter_mut().enumerate().take(9) {
            *length = i as u8 + 1;
        }
        lengths[9] = 10;
        lengths[29] = 10;
        let packed_dist = DistTable::from_lengths(&lengths, Completeness::Complete).unwrap();
        let dist = HuffmanTable::from_lengths(&lengths, Completeness::Complete).unwrap();
        let history: Vec<u8> = (0..32768).map(|i| (i * 43 + i / 137) as u8).collect();
        let mut writer = BitWriter::new();
        for i in 0..300 {
            writer.write_code(1, 7); // Fixed length symbol 257: length three.
            writer.write_code(0x3ff, 10); // Outside packed root; inside public 12-bit root.
            writer.write_bits(i, 13);
            writer.write_code(0x30 + i % 144, 8); // A literal between misses.
        }
        writer.write_code(0, 7); // EOB.
        let mut bytes = writer.finish();
        bytes.extend_from_slice(&[0xa5; 16]);
        for end in (0..bytes.len()).step_by(13).chain([bytes.len()]) {
            for extra in [263, 264, 265, 511, 512, 1200, 8192] {
                let mut actual = BitReader::new(&bytes[..end]);
                let mut reference = BitReader::new(&bytes[..end]);
                let mut out = history.clone();
                let mut expected = history.clone();
                let limit = history.len() + extra;
                let got = decode_tokens(&packed_lit, &packed_dist, &mut actual, &mut out, limit);
                let want = decode_huff_block(&lit, &dist, &mut reference, &mut expected, limit);
                assert_eq!(
                    (got, actual.bit_pos(), out),
                    (want, reference.bit_pos(), expected)
                );
            }
        }
    }

    fn canonical_codes(lengths: &[u8]) -> Vec<u32> {
        let mut count = [0u32; 16];
        for &l in lengths {
            count[usize::from(l)] += 1;
        }
        count[0] = 0;
        let mut next = [0u32; 16];
        for bits in 1..16 {
            next[bits] = (next[bits - 1] + count[bits - 1]) << 1;
        }
        lengths
            .iter()
            .map(|&l| {
                let code = next[usize::from(l)];
                next[usize::from(l)] += 1;
                code
            })
            .collect()
    }

    #[test]
    fn subtable_literal_codes_match_symbol_blocks() {
        // Dynamic literal/length codes up to fifteen bits exercise the
        // second-level path inside the batch, the tail and slice tokens.
        let history: Vec<u8> = (0..32768).map(|i| (i * 29 + i / 211) as u8).collect();
        let dist_lengths = [5u8; 32];
        let dist_codes = canonical_codes(&dist_lengths);
        let packed_dist = DistTable::from_lengths(&dist_lengths, Completeness::Complete).unwrap();
        let dist = HuffmanTable::from_lengths(&dist_lengths, Completeness::Complete).unwrap();
        for seed in 1..=6u64 {
            let lengths = crate::decode_table::tests::random_complete_lengths(seed, 286);
            assert!(lengths.iter().any(|&l| l >= 14));
            let codes = canonical_codes(&lengths);
            let packed_lit = LitTable::from_lengths(&lengths, Completeness::Complete).unwrap();
            let lit = HuffmanTable::from_lengths(&lengths, Completeness::Complete).unwrap();
            let mut state = seed.wrapping_mul(0x9e37_79b9_7f4a_7c15);
            let mut rand = move |n: u32| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state % u64::from(n)) as u32
            };
            let mut writer = BitWriter::new();
            for _ in 0..3000 {
                // Prefer long codes: half of all symbols are the longest ones.
                let symbol = if rand(2) == 0 {
                    let longest = *lengths.iter().max().unwrap();
                    let long: Vec<usize> = (0..286)
                        .filter(|&s| lengths[s] == longest && s != 256)
                        .collect();
                    long[rand(long.len() as u32) as usize]
                } else {
                    let mut s = rand(286) as usize;
                    if s == 256 {
                        s = 0;
                    }
                    s
                };
                writer.write_code(codes[symbol], u32::from(lengths[symbol]));
                if symbol > 256 {
                    let extra = u32::from(LENGTH_EXTRA[symbol - 257]);
                    writer.write_bits(rand(1 << extra), extra);
                    let d = rand(30) as usize;
                    writer.write_code(dist_codes[d], 5);
                    let extra = u32::from(DIST_EXTRA[d]);
                    writer.write_bits(rand(1 << extra), extra);
                }
            }
            writer.write_code(codes[256], u32::from(lengths[256]));
            let mut bytes = writer.finish();
            bytes.extend_from_slice(&[0xa5; 16]);
            for end in (0..bytes.len())
                .step_by(331)
                .chain([bytes.len() - 17, bytes.len()])
            {
                for additional in [0, 1, 263, 264, 265, 8192, 1 << 20] {
                    let mut actual = BitReader::new(&bytes[..end]);
                    let mut reference = BitReader::new(&bytes[..end]);
                    let mut out = history.clone();
                    let mut expected = history.clone();
                    let limit = history.len() + additional;
                    let got =
                        decode_tokens(&packed_lit, &packed_dist, &mut actual, &mut out, limit);
                    let want = decode_huff_block(&lit, &dist, &mut reference, &mut expected, limit);
                    assert_eq!(
                        (got, actual.bit_pos(), out),
                        (want, reference.bit_pos(), expected),
                        "seed={seed}, end={end}, additional={additional}"
                    );
                }
            }
        }
    }

    #[test]
    fn packed_blocks_match_symbol_blocks_across_copy_and_batch_boundaries() {
        // The public symbol-table path is independently compared with a
        // canonical/bytewise reference in tests/block_fast_tests.rs.
        let (packed_lit, packed_dist) = fixed_tables();
        let lit = crate::huffman::fixed_litlen();
        let dist = crate::huffman::fixed_dist();
        let history: Vec<u8> = (0..32768).map(|i| (i * 31 + i / 251) as u8).collect();
        let mut tokens = Vec::new();
        for distance in (1..=33).chain([255, 256, 257, 32767, 32768]) {
            for len in (3..=33).chain([255, 256, 257, 258]) {
                tokens.push(Token::Match {
                    len,
                    dist: distance,
                });
                tokens.push(Token::Literal((len + distance) as u8));
            }
        }
        for offset in 0..8 {
            let mut writer = BitWriter::new();
            writer.write_bits(0, offset);
            crate::encode_fixed::emit_fixed_block(&mut writer, true, tokens.clone());
            let mut bytes = writer.finish();
            bytes.extend_from_slice(&[0xa5; 16]);
            for end in (0..bytes.len()).step_by(127).chain([bytes.len()]) {
                for additional in [0, 1, 7, 8, 15, 16, 263, 264, 265, 8191, 8192, 8193, 200000] {
                    let mut actual = BitReader::new(&bytes[..end]);
                    let mut reference = BitReader::new(&bytes[..end]);
                    actual.skip_bits(offset as usize + 3);
                    reference.skip_bits(offset as usize + 3);
                    let mut out = history.clone();
                    let mut expected = history.clone();
                    let limit = history.len() + additional;
                    let got =
                        decode_tokens(&packed_lit, &packed_dist, &mut actual, &mut out, limit);
                    let want = decode_huff_block(&lit, &dist, &mut reference, &mut expected, limit);
                    assert_eq!(
                        (got, actual.bit_pos(), out),
                        (want, reference.bit_pos(), expected),
                        "offset={offset}, end={end}, additional={additional}"
                    );
                }
            }
        }
    }
}
