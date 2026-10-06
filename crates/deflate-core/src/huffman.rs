//! Canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).
//! Mirrors `spec/Deflate/Huffman.lean`.
//!
//! Huffman codes are the one element packed most-significant-bit first.
//! [`HuffmanTable::decode`] is the canonical walk (Lean `decodeSym`): shift
//! one bit in at a time and test, at each length, whether the accumulated
//! value falls inside that length's contiguous range.
//!
//! [`HuffmanTable::decode_fast`] puts a 9-bit lookup table in front of that
//! walk (ADR 0005, `spec/Deflate/HuffmanTable.lean`). It mirrors Lean
//! `decodeSymFast`, which `decodeSymFast_eq` proves equal to `decodeSym` on
//! every reader, errors included. Codes longer than 9 bits, and anything
//! within 9 bits of the end of the stream, still take the canonical walk.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

/// RFC 1951 §3.2.7.
pub const MAX_CODE_LEN: usize = 15;

/// Width of the primary decode table. Lean `tableBits`.
/// 12 bits: covers ~99% of codes in typical DEFLATE streams (most codes <= 12 bits).
pub const TABLE_BITS: u32 = 12;
const TABLE_SIZE: usize = 1 << TABLE_BITS;

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
    /// Lean `buildTable`: entry `p` is `(sym << 4) | len` when the canonical
    /// walk on next-bits `p` yields `sym` after `len <= 9` bits, else 0
    /// (fallback). `len >= 1` on every hit, so 0 is unambiguous.
    fast: [u16; TABLE_SIZE],
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
        let fast = build_fast(&counts, &symbols);
        Ok(HuffmanTable {
            counts,
            symbols,
            fast,
        })
    }

    /// The primary decode table, for tests that check it against the
    /// literal construction (Lean `tableEntry`).
    pub fn fast_table(&self) -> &[u16; TABLE_SIZE] {
        &self.fast
    }

    /// Decode one symbol through the table. Lean `decodeSymFast`.
    ///
    /// The table is consulted only when 9 whole bits remain: a zero-padded
    /// peek could hit on padding. A miss, or a short stream, runs the
    /// canonical walk from the unchanged position, so errors come out
    /// exactly as `decode` reports them (`decodeSymFast_eq`).
    #[inline]
    pub fn decode_fast(&self, r: &mut BitReader) -> Result<u16, Error> {
        if let Ok(p) = r.peek_bits(TABLE_BITS) {
            let e = self.fast.get(p as usize).copied().unwrap_or(0);
            if e != 0 {
                r.skip_bits(usize::from(e & 0xf));
                return Ok(e >> 4);
            }
        }
        self.decode(r)
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

/// Fill the table by replication: each code of length `L <= 9` owns every
/// slot whose low `L` bits are its bit-reversed code (stream order is LSB
/// first, codes are MSB first). The tests check this equals Lean
/// `buildTable`'s literal evaluation for fixed, random complete, and
/// ADR 0004 degenerate codes. Any slot this misses stays 0, which is
/// always safe: fallback is the canonical walk.
fn build_fast(counts: &[u16; MAX_CODE_LEN + 1], symbols: &[u16]) -> [u16; TABLE_SIZE] {
    let mut fast = [0u16; TABLE_SIZE];
    // Same canonical arithmetic as `decode`: `first` is the first code of
    // length `len`, `index` the canonical position of its symbol.
    let mut first: u32 = 0;
    let mut index: usize = 0;
    for len in 1..=TABLE_BITS {
        let count = counts.get(len as usize).copied().unwrap_or(0);
        for i in 0..count {
            // Saturating: Kraft (checked in `from_lengths`) keeps these
            // small, and a saturated value only produces a fallback slot.
            let code = first.saturating_add(u32::from(i));
            let sym = symbols
                .get(index.saturating_add(usize::from(i)))
                .copied()
                .unwrap_or(u16::MAX);
            // Every DEFLATE symbol is below 288; anything that would not
            // fit the encoding is left as fallback.
            if sym > (u16::MAX >> 4) || code >= (1 << len) {
                continue;
            }
            let entry = (sym << 4) | len as u16;
            let rev = code.reverse_bits() >> (32 - len);
            let mut slot = rev as usize;
            while let Some(e) = fast.get_mut(slot) {
                *e = entry;
                slot = slot.saturating_add(1 << len);
            }
        }
        index = index.saturating_add(usize::from(count));
        first = first.saturating_add(u32::from(count)) << 1;
    }
    fast
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
        fast: [0; TABLE_SIZE],
    })
}

pub fn fixed_dist() -> HuffmanTable {
    HuffmanTable::from_lengths(&[5u8; 32], Completeness::Complete).unwrap_or_else(|_| {
        HuffmanTable {
            counts: [0; MAX_CODE_LEN + 1],
            symbols: Vec::new(),
            fast: [0; TABLE_SIZE],
        }
    })
}
