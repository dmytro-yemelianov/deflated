//! The minimal encoder (spec §17 M6). Stored blocks only.
//! Mirrors `spec/Deflate/Encode.lean`.
//!
//! This makes output slightly larger than input, which is what a stored-block
//! encoder is for: it establishes framing correctness before any compression
//! ratio work (spec §17 M7, a later plan).

use alloc::vec::Vec;

/// RFC 1951 §3.2.4: LEN is 16 bits.
pub const MAX_STORED: usize = 65535;

/// Encode `input` as a sequence of stored blocks. Empty input yields one
/// final block with LEN = 0, because a stream with no blocks is not valid
/// DEFLATE.
pub fn deflate_stored(input: &[u8]) -> Vec<u8> {
    let blocks = input.len().div_ceil(MAX_STORED).max(1);
    let mut out = Vec::with_capacity(input.len() + 5 * blocks);
    let mut rest = input;
    loop {
        let take = rest.len().min(MAX_STORED);
        let (chunk, tail) = rest.split_at(take);
        let is_final = tail.is_empty();
        // BFINAL in bit 0, BTYPE = 00 in bits 1-2, then five padding bits to
        // the byte boundary that `read_stored` aligns to.
        out.push(u8::from(is_final));
        let len = take as u16;
        out.extend_from_slice(&len.to_le_bytes());
        out.extend_from_slice(&(!len).to_le_bytes());
        out.extend_from_slice(chunk);
        if is_final {
            return out;
        }
        rest = tail;
    }
}
