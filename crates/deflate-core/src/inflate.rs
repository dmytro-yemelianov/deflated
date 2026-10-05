//! The decoder driver (RFC 1951 §3.2.3): read blocks until BFINAL.
//! Mirrors `spec/Deflate/Decode.lean`.

use crate::bitstream::BitReader;
use crate::block::{
    BlockType, decode_huff_block, read_block_header, read_dynamic_tables, read_stored,
};
use crate::error::Error;
use crate::huffman::{fixed_dist, fixed_litlen};
use alloc::vec::Vec;

/// The limit [`inflate`] uses: 1 GiB. Chosen so that the convenience entry
/// point cannot be turned into an out-of-memory condition by a stream a few
/// hundred bytes long, while staying far above any realistic document.
/// Callers handling untrusted input should pass their own, smaller, limit
/// to [`inflate_with_limit`] (spec §11).
pub const DEFAULT_LIMIT: usize = 1 << 30;

/// Decode, with [`DEFAULT_LIMIT`] as the ceiling.
pub fn inflate(input: &[u8]) -> Result<Vec<u8>, Error> {
    inflate_with_limit(input, DEFAULT_LIMIT)
}

/// Decode, refusing to produce more than `limit` bytes.
///
/// The limit is checked before every append and before every back-copy, so a
/// stream that would expand past it is refused without allocating past it.
/// `Ok(v)` implies `v.len() <= limit`.
pub fn inflate_with_limit(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut r = BitReader::new(input);
    let mut out: Vec<u8> = Vec::new();
    loop {
        let header = read_block_header(&mut r)?;
        match header.btype {
            BlockType::Stored => {
                let budget = limit.saturating_sub(out.len());
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
