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
/// Mirrors `spec/Deflate/Block.lean`'s `decodeHuffBlock`.
pub fn decode_huff_block(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    loop {
        let sym = lit.decode(r)?;
        if sym < 256 {
            if out.len() >= limit {
                return Err(Error::OutputLimitExceeded);
            }
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let len = read_length(sym, r)?;
            let dsym = dist.decode(r)?;
            let d = read_distance(dsym, r)?;
            if out.len().saturating_add(len) > limit {
                return Err(Error::OutputLimitExceeded);
            }
            copy_back(out, d, len)?;
        }
        // No explicit fuel: `lit.decode` consumes at least one bit on every
        // path that returns `Ok`, and the stream is finite, so the loop
        // terminates with `UnexpectedEof` if nothing else stops it first.
        // `spec/Deflate/Properties.lean`'s `decodeHuffBlock_progress` is the
        // model's statement of that argument.
    }
}
