//! The decoder driver (RFC 1951 §3.2.3): read blocks until BFINAL.
//! Mirrors `spec/Deflate/Decode.lean`.

use crate::bitstream::BitReader;
use crate::block::{BlockType, read_block_header, read_stored};
use crate::error::Error;
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
        let budget = limit - out.len();
        match header.btype {
            BlockType::Stored => read_stored(&mut r, &mut out, budget)?,
            // Tasks 14 and 16 replace these.
            BlockType::Fixed | BlockType::Dynamic => return Err(Error::InvalidBlockType),
        }
        if header.is_final {
            return Ok(out);
        }
    }
}
