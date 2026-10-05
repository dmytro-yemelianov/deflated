//! The decoder driver (RFC 1951 §3.2.3): read blocks until BFINAL.
//! Mirrors `spec/Deflate/Decode.lean`.

use crate::bitstream::BitReader;
use crate::block::{
    BlockType, decode_huff_block, read_block_header, read_dynamic_tables, read_stored,
};
use crate::error::Error;
use crate::huffman::{fixed_dist, fixed_litlen};
use alloc::vec::Vec;

/// Decode with no output limit. Suitable only for input you produced
/// yourself. For anything from the network or a file you did not write, use
/// [`inflate_with_limit`] (spec §11).
pub fn inflate(input: &[u8]) -> Result<Vec<u8>, Error> {
    inflate_with_limit(input, usize::MAX)
}

/// Decode, refusing to produce more than `limit` bytes.
pub fn inflate_with_limit(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut r = BitReader::new(input);
    let mut out: Vec<u8> = Vec::new();
    loop {
        let header = read_block_header(&mut r)?;
        match header.btype {
            BlockType::Stored => {
                let budget = limit - out.len();
                read_stored(&mut r, &mut out, budget)?;
            }
            BlockType::Fixed => {
                let lit = fixed_litlen();
                let dst = fixed_dist();
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
            BlockType::Dynamic => {
                let (lit, dst) = read_dynamic_tables(&mut r)?;
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
        }
        if header.is_final {
            return Ok(out);
        }
    }
}
