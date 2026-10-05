//! LSB-first bit reading (RFC 1951 §3.1.1).
//!
//! Mirrors `spec/Deflate/Bitstream.lean` function for function. Two places
//! differ in shape. First, the Lean reader is a value, so a failed read
//! simply returns `none` and the caller keeps the old reader. Rust mutates in
//! place, so every fallible read checks its whole width *before* consuming
//! anything. `short_read_is_atomic_and_leaves_position_untouched` pins that.
//! Second, `read_bits` takes all `n` bits from one byte window instead of
//! looping over `read_bit` like Lean `readBits`; the tests check it against a
//! bit-by-bit reference.

use crate::error::Error;
use alloc::vec::Vec;

/// A position in a compressed stream.
pub struct BitReader<'a> {
    bytes: &'a [u8],
    /// Bit offset from the start of `bytes`, not a byte offset.
    pos: usize,
}

impl<'a> BitReader<'a> {
    pub fn new(bytes: &'a [u8]) -> Self {
        BitReader { bytes, pos: 0 }
    }

    /// Current bit offset.
    pub fn bit_pos(&self) -> usize {
        self.pos
    }

    /// Total bits in the stream. `bytes.len()` is bounded by `isize::MAX`, so
    /// this cannot overflow on any platform Rust supports.
    pub fn bit_len(&self) -> usize {
        self.bytes.len() * 8
    }

    /// One bit, least significant first within each byte.
    pub fn read_bit(&mut self) -> Result<u32, Error> {
        let byte = match self.bytes.get(self.pos / 8) {
            Some(b) => *b,
            None => return Err(Error::UnexpectedEof),
        };
        let bit = (byte >> (self.pos % 8)) & 1;
        self.pos += 1;
        Ok(bit as u32)
    }

    /// `n` bits, least significant first. `n` must be at most 32; a larger
    /// request is a caller bug and returns `InvalidCode` rather than
    /// truncating silently. All-or-nothing: on `UnexpectedEof` the position
    /// is unchanged.
    pub fn read_bits(&mut self, n: u32) -> Result<u32, Error> {
        let v = self.peek_bits(n)?;
        // `peek_bits` succeeded, so pos + n <= bit_len: no overflow.
        self.pos += n as usize;
        Ok(v)
    }

    /// What `read_bits(n)` would return, without consuming anything. Fails
    /// exactly when `read_bits(n)` would, so it never zero-pads past the end
    /// (ADR 0005; Lean `readBits_some`, `readBits_eof`).
    pub fn peek_bits(&self, n: u32) -> Result<u32, Error> {
        if n > 32 {
            return Err(Error::InvalidCode);
        }
        if self.pos + (n as usize) > self.bit_len() {
            return Err(Error::UnexpectedEof);
        }
        // Same value as `n` calls to `read_bit` (the Lean `readBits` loop),
        // assembled at once: 7 bits of offset + 32 bits fit in 5 bytes.
        // Bytes past the end read as 0; the check above guarantees the
        // wanted bits all lie inside the stream.
        let first = self.pos / 8;
        let mut window: u64 = 0;
        for k in 0..5 {
            let byte = first
                .checked_add(k)
                .and_then(|i| self.bytes.get(i))
                .copied()
                .unwrap_or(0);
            window |= u64::from(byte) << (8 * k);
        }
        // n <= 32, so the shift cannot overflow a u64.
        let mask = (1u64 << n) - 1;
        Ok(((window >> (self.pos % 8)) & mask) as u32)
    }

    /// Consume `n` bits already examined with `peek_bits(m)`, `m >= n`.
    /// Saturating, so a misuse cannot panic; it would only leave the
    /// reader past the end, where every read is `UnexpectedEof`.
    pub fn skip_bits(&mut self, n: usize) {
        self.pos = self.pos.saturating_add(n);
    }

    /// Skip to the next byte boundary (RFC 1951 §3.2.4).
    pub fn align_to_byte(&mut self) {
        self.pos = self.pos.div_ceil(8) * 8;
    }

    /// A byte-aligned little-endian `u16`. Aligns first, as `LEN`/`NLEN` need.
    pub fn read_aligned_u16_le(&mut self) -> Result<u16, Error> {
        let start = self.pos;
        self.align_to_byte();
        if self.pos + 16 > self.bit_len() {
            self.pos = start;
            return Err(Error::UnexpectedEof);
        }
        let lo = self.read_bits(8)? as u16;
        let hi = self.read_bits(8)? as u16;
        Ok(lo | (hi << 8))
    }

    /// Append `n` byte-aligned bytes to `out`. Aligns first.
    pub fn read_aligned_into(&mut self, out: &mut Vec<u8>, n: usize) -> Result<(), Error> {
        let start = self.pos;
        self.align_to_byte();
        let byte_start = self.pos / 8;
        let end = match byte_start.checked_add(n) {
            Some(e) if e <= self.bytes.len() => e,
            _ => {
                self.pos = start;
                return Err(Error::UnexpectedEof);
            }
        };
        match self.bytes.get(byte_start..end) {
            Some(src) => out.extend_from_slice(src),
            None => {
                self.pos = start;
                return Err(Error::UnexpectedEof);
            }
        }
        self.pos = end * 8;
        Ok(())
    }
}
