//! LSB-first bit writing (RFC 1951 §3.1.1), the inverse of `bitstream`.
//!
//! Mirrors `spec/Deflate/BitWriter.lean`. Whole bytes are flushed eagerly,
//! so the pending buffer holds fewer than 8 bits between calls.

use alloc::vec::Vec;

#[derive(Debug, Default)]
pub struct BitWriter {
    bytes: Vec<u8>,
    /// Pending low bits, not yet a whole byte.
    acc: u64,
    /// Number of valid bits in `acc`, always < 8 between calls.
    nacc: u32,
}

impl BitWriter {
    pub fn new() -> Self {
        BitWriter {
            bytes: Vec::new(),
            acc: 0,
            nacc: 0,
        }
    }

    /// Append the low `n` bits of `v`, least significant first (Lean
    /// `writeBits`). `n > 32` is a caller bug and is clamped to 32; bits of
    /// `v` above `n` are ignored.
    pub fn write_bits(&mut self, v: u32, n: u32) {
        let n = n.min(32);
        let mask = (1u64 << n) - 1;
        // nacc < 8 and n <= 32, so the shift and the sum stay within 64 bits.
        self.acc |= (u64::from(v) & mask) << self.nacc;
        self.nacc += n;
        while self.nacc >= 8 {
            self.bytes.push((self.acc & 0xFF) as u8);
            self.acc >>= 8;
            self.nacc -= 8;
        }
    }

    /// Append a Huffman code MSB-first: `write_bits` of the bit-reversed
    /// code (Lean `writeCode`). `len` is at most 15 for DEFLATE.
    pub fn write_code(&mut self, code: u32, len: u32) {
        let len = len.min(32);
        let mut rev = 0u32;
        for i in 0..len {
            rev |= ((code >> i) & 1) << (len - 1 - i);
        }
        self.write_bits(rev, len);
    }

    /// Bits written so far, counting the open byte.
    pub fn bit_len(&self) -> usize {
        self.bytes.len() * 8 + self.nacc as usize
    }

    /// Pad the open byte with zeros and return the bytes (Lean `finish`).
    pub fn finish(mut self) -> Vec<u8> {
        if self.nacc > 0 {
            self.bytes.push((self.acc & 0xFF) as u8);
        }
        self.bytes
    }
}
