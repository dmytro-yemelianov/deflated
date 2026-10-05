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
    r.read_aligned_into(out, len)
}

use crate::huffman::HuffmanTable;
use crate::lz77::{copy_back, read_distance, read_length};

/// Decode one Huffman-coded block body. Serves both fixed and dynamic
/// blocks; they differ only in where `lit` and `dist` come from.
/// `limit` is the absolute ceiling on `out.len()`, checked *before* each
/// append, so a bomb never allocates past it.
/// Mirrors `spec/Deflate/Block.lean`'s `decodeHuffBlock`. Symbols are read
/// with `decode_fast` (Lean `decodeSymFast`) where the model calls
/// `decodeSym`; `decodeSymFast_eq` says the two agree on every reader.
pub fn decode_huff_block(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    loop {
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

use crate::huffman::Completeness;

/// RFC 1951 §3.2.7: the order in which code-length code lengths appear.
pub const CL_ORDER: [usize; 19] = [
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

/// Read a dynamic block's two Huffman tables (RFC 1951 §3.2.7).
/// Mirrors `spec/Deflate/Block.lean`'s `readDynamicCodes`.
pub fn read_dynamic_tables(r: &mut BitReader) -> Result<(HuffmanTable, HuffmanTable), Error> {
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
    let cl = HuffmanTable::from_lengths(&cl_lengths, Completeness::Complete)?;

    let total = nlen + ndist;
    let mut lengths = alloc::vec![0u8; 0];
    lengths.reserve(total);
    while lengths.len() < total {
        // The table is built anyway; `decodeSymFast_eq` holds for every code.
        let sym = cl.decode_fast(r)?;
        match sym {
            0..=15 => lengths.push(sym as u8),
            16 => {
                let prev = match lengths.last() {
                    Some(p) => *p,
                    None => return Err(Error::InvalidHuffmanTree),
                };
                let n = 3 + r.read_bits(2)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, prev);
            }
            17 => {
                let n = 3 + r.read_bits(3)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            18 => {
                let n = 11 + r.read_bits(7)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            _ => return Err(Error::InvalidHuffmanTree),
        }
    }

    let (lit_lens, dist_lens) = match lengths.split_at_checked(nlen) {
        Some(p) => p,
        None => return Err(Error::InvalidHuffmanTree),
    };
    let lit = HuffmanTable::from_lengths(lit_lens, Completeness::Complete)?;
    // ADR 0004: only the distance tree is allowed to be degenerate.
    let dist = HuffmanTable::from_lengths(dist_lens, Completeness::AllowDegenerate)?;
    Ok((lit, dist))
}
