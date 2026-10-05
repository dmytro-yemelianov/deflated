//! The Charon/Aeneas spike (M0). Deliberately standalone: it duplicates the
//! shape of `deflate_core::bitstream` rather than importing it, so a
//! translation failure here is a fact about the toolchain, not about a
//! half-written crate.
#![no_std]
#![forbid(unsafe_code)]

pub struct Reader {
    pub bytes: [u8; 8],
    pub pos: u32,
}

/// Read one bit, LSB-first within each byte. Returns `None` past the end.
pub fn read_bit(r: &Reader) -> Option<(bool, u32)> {
    if r.pos >= 64 {
        return None;
    }
    let byte = r.bytes[(r.pos / 8) as usize];
    let bit = (byte >> (r.pos % 8)) & 1;
    Some((bit == 1, r.pos + 1))
}
