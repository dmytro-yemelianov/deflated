//! Canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).
//! Mirrors `spec/Deflate/Huffman.lean`.
//!
//! Huffman codes are the one element packed most-significant-bit first.
//! Decoding shifts one bit in at a time and tests, at each length, whether the
//! accumulated value falls inside that length's contiguous range. No decode
//! table is built, which keeps the code small and the correspondence with the
//! model direct; Task 24 may revisit that for speed, under ADR.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

/// RFC 1951 §3.2.7.
pub const MAX_CODE_LEN: usize = 15;

/// Whether an incomplete code is tolerable here. See ADR 0004.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Completeness {
    /// Literal/length and code-length trees: the code must be complete.
    Complete,
    /// Distance trees: zero or one used symbol is also accepted, because
    /// that is what real encoders emit for a block with no matches.
    AllowDegenerate,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HuffmanTable {
    /// `counts[l]` is how many symbols have length `l`. `counts[0]` is 0.
    counts: [u16; MAX_CODE_LEN + 1],
    /// Symbols ordered by (length, symbol): the canonical order.
    symbols: Vec<u16>,
}

impl HuffmanTable {
    pub fn from_lengths(lengths: &[u8], completeness: Completeness) -> Result<Self, Error> {
        let mut counts = [0u16; MAX_CODE_LEN + 1];
        let mut used = 0usize;
        for &l in lengths {
            let l = l as usize;
            if l > MAX_CODE_LEN {
                return Err(Error::InvalidHuffmanTree);
            }
            if l != 0 {
                used += 1;
                match counts.get_mut(l) {
                    Some(c) => *c += 1,
                    None => return Err(Error::InvalidHuffmanTree),
                }
            }
        }

        // Kraft check, carried as the number of still-unassigned patterns.
        // Going negative means over-subscribed; ending positive means
        // incomplete. i32 cannot overflow here: the loop runs 15 times and
        // each count is at most lengths.len() <= 288 + 32.
        let mut left: i32 = 1;
        for &count in &counts[1..=MAX_CODE_LEN] {
            left <<= 1;
            left -= i32::from(count);
            if left < 0 {
                return Err(Error::InvalidHuffmanTree);
            }
        }
        if left > 0 {
            // Incomplete.
            match completeness {
                Completeness::Complete => return Err(Error::InvalidHuffmanTree),
                Completeness::AllowDegenerate if used <= 1 => {}
                Completeness::AllowDegenerate => return Err(Error::InvalidHuffmanTree),
            }
        }

        // Offsets, then symbols in (length, symbol) order.
        let mut offs = [0u16; MAX_CODE_LEN + 2];
        for l in 1..=MAX_CODE_LEN {
            offs[l + 1] = offs[l] + counts[l];
        }
        let mut symbols = alloc::vec![0u16; used];
        for (sym, &l) in lengths.iter().enumerate() {
            let l = l as usize;
            if l == 0 {
                continue;
            }
            let idx = offs[l] as usize;
            match symbols.get_mut(idx) {
                Some(slot) => *slot = sym as u16,
                None => return Err(Error::InvalidHuffmanTree),
            }
            offs[l] += 1;
        }
        Ok(HuffmanTable { counts, symbols })
    }

    /// Decode one symbol. Consumes between 1 and `MAX_CODE_LEN` bits.
    pub fn decode(&self, r: &mut BitReader) -> Result<u16, Error> {
        let mut code: u32 = 0;
        let mut first: u32 = 0;
        let mut index: u32 = 0;
        for l in 1..=MAX_CODE_LEN {
            code |= r.read_bit()?;
            let count = u32::from(self.counts[l]);
            if code < first + count {
                let i = (index + (code - first)) as usize;
                return match self.symbols.get(i) {
                    Some(s) => Ok(*s),
                    None => Err(Error::InvalidCode),
                };
            }
            index += count;
            first = (first + count) << 1;
            code <<= 1;
        }
        Err(Error::InvalidCode)
    }
}

pub fn fixed_litlen() -> HuffmanTable {
    let mut l = alloc::vec![8u8; 288];
    for e in l.iter_mut().take(256).skip(144) {
        *e = 9;
    }
    for e in l.iter_mut().take(280).skip(256) {
        *e = 7;
    }
    // Lengths 8,9,7,8 give a Kraft sum of exactly 2^15 — see Lean's
    // `fixedLitLen_valid`. The unwrap-free construction keeps the no-panic
    // rule: a construction error here would be a bug in this function, so
    // report it as one rather than panicking.
    HuffmanTable::from_lengths(&l, Completeness::Complete).unwrap_or_else(|_| HuffmanTable {
        counts: [0; MAX_CODE_LEN + 1],
        symbols: Vec::new(),
    })
}

pub fn fixed_dist() -> HuffmanTable {
    HuffmanTable::from_lengths(&[5u8; 32], Completeness::Complete).unwrap_or_else(|_| {
        HuffmanTable {
            counts: [0; MAX_CODE_LEN + 1],
            symbols: Vec::new(),
        }
    })
}
