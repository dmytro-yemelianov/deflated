//! Canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).
//! Mirrors `spec/Deflate/Huffman.lean`.
//!
//! Huffman codes are the one element packed most-significant-bit first.
//! [`HuffmanTable::decode`] is the canonical walk (Lean `decodeSym`): shift
//! one bit in at a time and test, at each length, whether the accumulated
//! value falls inside that length's contiguous range.
//!
//! [`HuffmanTable::decode_fast`] puts a 12-bit lookup table in front of that
//! walk (ADR 0005, `spec/Deflate/HuffmanTable.lean`). It mirrors Lean
//! `decodeSymFast`, which `decodeSymFast_eq` proves equal to `decodeSym` on
//! every reader, errors included. Codes longer than 12 bits, and anything
//! within 12 bits of the end of the stream, still take the canonical walk.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::{borrow::Cow, boxed::Box};

/// RFC 1951 §3.2.7.
pub const MAX_CODE_LEN: usize = 15;

/// Width of the primary decode table. Lean `tableBits`.
/// Codes up to 12 bits resolve in one lookup; longer codes use the walk.
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
    symbols: Cow<'static, [u16]>,
    /// Lean `buildTable`: entry `p` is `(sym << 4) | len` when the canonical
    /// walk on next-bits `p` yields `sym` after `len <= TABLE_BITS` bits, else 0
    /// (fallback). `len >= 1` on every hit, so 0 is unambiguous.
    fast: DecodeTable,
}

#[derive(Debug, Clone)]
enum DecodeTable {
    Fixed(&'static [u16; TABLE_SIZE]),
    Built(Box<[u16; TABLE_SIZE]>),
}

impl DecodeTable {
    fn entries(&self) -> &[u16; TABLE_SIZE] {
        match self {
            Self::Fixed(table) => table,
            Self::Built(table) => table,
        }
    }
}

impl PartialEq for DecodeTable {
    fn eq(&self, other: &Self) -> bool {
        self.entries() == other.entries()
    }
}

impl Eq for DecodeTable {}

impl HuffmanTable {
    /// Build canonical codes from lengths. Active symbol indices must fit
    /// `u16`; invalid lengths, trees or indices return `InvalidHuffmanTree`.
    pub fn from_lengths(lengths: &[u8], completeness: Completeness) -> Result<Self, Error> {
        let mut symbols = alloc::vec::Vec::new();
        let counts = prepare(lengths, completeness, &mut symbols)?;
        let fast = new_fast(&counts, &symbols);
        Ok(HuffmanTable {
            counts,
            symbols: Cow::Owned(symbols),
            fast: DecodeTable::Built(fast),
        })
    }

    // Private: callers must not decode after a failed rebuild. The next
    // successful rebuild replaces all symbols/counts/entries before use.
    #[cfg(test)]
    pub(crate) fn rebuild(
        &mut self,
        lengths: &[u8],
        completeness: Completeness,
    ) -> Result<(), Error> {
        let counts = prepare(lengths, completeness, self.symbols.to_mut())?;
        let fast = match &mut self.fast {
            DecodeTable::Built(fast) => fast,
            DecodeTable::Fixed(_) => {
                *self = Self::from_lengths(lengths, completeness)?;
                return Ok(());
            }
        };
        build_fast(&counts, &self.symbols, fast);
        self.counts = counts;
        Ok(())
    }

    /// The primary decode table, for tests that check it against the
    /// literal construction (Lean `tableEntry`).
    pub fn fast_table(&self) -> &[u16; TABLE_SIZE] {
        self.fast.entries()
    }

    /// Decode one symbol through the table. Lean `decodeSymFast`.
    ///
    /// The table is consulted only when 12 whole bits remain: a zero-padded
    /// peek could hit on padding. A miss, or a short stream, runs the
    /// canonical walk from the unchanged position, so errors come out
    /// exactly as `decode` reports them (`decodeSymFast_eq`).
    #[inline]
    pub fn decode_fast(&self, r: &mut BitReader) -> Result<u16, Error> {
        if let Ok(p) = r.peek_bits(TABLE_BITS) {
            let e = self.fast_table().get(p as usize).copied().unwrap_or(0);
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

// Canonical fallback for action tables, checked against the public walk.
// Keep the public method in its original form so its compact decoder retains
// the same optimization opportunities for short streams.
#[inline(always)]
pub(crate) fn decode_canonical(
    counts: &[u16; MAX_CODE_LEN + 1],
    symbols: &[u16],
    r: &mut BitReader<'_>,
) -> Result<u16, Error> {
    let mut code: u32 = 0;
    let mut first: u32 = 0;
    let mut index: u32 = 0;
    for &count in &counts[1..] {
        code |= r.read_bit()?;
        let count = u32::from(count);
        if code < first + count {
            let i = (index + (code - first)) as usize;
            return match symbols.get(i) {
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

#[inline]
pub(crate) fn prepare(
    lengths: &[u8],
    completeness: Completeness,
    symbols: &mut alloc::vec::Vec<u16>,
) -> Result<[u16; MAX_CODE_LEN + 1], Error> {
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
                Some(c) => *c = c.checked_add(1).ok_or(Error::InvalidHuffmanTree)?,
                None => return Err(Error::InvalidHuffmanTree),
            }
        }
    }

    // Kraft check, carried as the number of still-unassigned patterns.
    // Going negative means over-subscribed; ending positive means
    // incomplete. i32 cannot overflow here: the loop runs 15 times and
    // each count is at most u16::MAX, including public non-DEFLATE inputs.
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
    symbols.clear();
    symbols.resize(used, 0);
    for (sym, &l) in lengths.iter().enumerate() {
        let l = l as usize;
        if l == 0 {
            continue;
        }
        let idx = offs[l] as usize;
        match symbols.get_mut(idx) {
            Some(slot) => *slot = u16::try_from(sym).map_err(|_| Error::InvalidHuffmanTree)?,
            None => return Err(Error::InvalidHuffmanTree),
        }
        offs[l] += 1;
    }
    Ok(counts)
}

/// Grow the populated prefix one bit at a time. At width `L`, codes of
/// length `L` are inserted once at their reversed index. Copying that prefix
/// into its upper half replicates every shorter code for the next bit.
/// Thus each code owns every slot whose low bits are its reversed code
/// (stream order is LSB first, codes are MSB first). The tests check this equals Lean
/// `buildTable`'s literal evaluation for fixed, random complete, and
/// ADR 0004 degenerate codes. Any slot this misses stays 0, which is
/// always safe: fallback is the canonical walk.
fn new_fast(counts: &[u16; MAX_CODE_LEN + 1], symbols: &[u16]) -> Box<[u16; TABLE_SIZE]> {
    let mut fast = Box::new([0; TABLE_SIZE]);
    build_fast(counts, symbols, &mut fast);
    fast
}

#[inline(always)]
fn build_fast(counts: &[u16; MAX_CODE_LEN + 1], symbols: &[u16], fast: &mut [u16; TABLE_SIZE]) {
    // Every larger prefix is overwritten by doubling below. Clearing the
    // initial two slots therefore clears all stale hits, including empty trees.
    fast[..2].fill(0);
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
            if let Some(e) = fast.get_mut(rev as usize) {
                *e = entry;
            }
        }
        index = index.saturating_add(usize::from(count));
        first = first.saturating_add(u32::from(count)) << 1;
        if len < TABLE_BITS {
            // Complete/Kraft-checked codes cannot overwrite a shorter code.
            // Unassigned patterns remain zero and keep canonical fallback.
            let filled = 1usize << len;
            fast.copy_within(..filled, filled);
        }
    }
}

// Fixed tables are immutable RFC constants. Construct once at compile time,
// sharing both the symbol order and lookup table across blocks and calls.
const fn fixed_symbols() -> [u16; 288] {
    let mut symbols = [0; 288];
    let mut i = 0;
    while i < 288 {
        symbols[i] = if i < 24 {
            256 + i as u16
        } else if i < 168 {
            (i - 24) as u16
        } else if i < 176 {
            280 + (i - 168) as u16
        } else {
            144 + (i - 176) as u16
        };
        i += 1;
    }
    symbols
}

const fn fixed_lookup(distance: bool) -> [u16; TABLE_SIZE] {
    let mut table = [0; TABLE_SIZE];
    let count = if distance { 32 } else { 288 };
    let mut sym = 0u16;
    while sym < count {
        let (code, len): (u16, u32) = if distance {
            (sym, 5)
        } else if sym < 144 {
            (0x30 + sym, 8)
        } else if sym < 256 {
            (0x190 + sym - 144, 9)
        } else if sym < 280 {
            (sym - 256, 7)
        } else {
            (0xc0 + sym - 280, 8)
        };
        let mut slot = (code.reverse_bits() >> (16 - len)) as usize;
        while slot < TABLE_SIZE {
            table[slot] = (sym << 4) | len as u16;
            slot += 1 << len;
        }
        sym += 1;
    }
    table
}

static FIXED_LIT_SYMBOLS: [u16; 288] = fixed_symbols();
static FIXED_DIST_SYMBOLS: [u16; 32] = {
    let mut symbols = [0; 32];
    let mut i = 0;
    while i < 32 {
        symbols[i] = i as u16;
        i += 1;
    }
    symbols
};
static FIXED_LIT_TABLE: [u16; TABLE_SIZE] = fixed_lookup(false);
static FIXED_DIST_TABLE: [u16; TABLE_SIZE] = fixed_lookup(true);

pub(crate) fn fixed_lit_parts() -> ([u16; MAX_CODE_LEN + 1], &'static [u16]) {
    let table = fixed_litlen();
    (table.counts, &FIXED_LIT_SYMBOLS)
}

pub(crate) fn fixed_dist_parts() -> ([u16; MAX_CODE_LEN + 1], &'static [u16]) {
    let table = fixed_dist();
    (table.counts, &FIXED_DIST_SYMBOLS)
}

pub fn fixed_litlen() -> HuffmanTable {
    let mut counts = [0; MAX_CODE_LEN + 1];
    counts[7] = 24;
    counts[8] = 152;
    counts[9] = 112;
    HuffmanTable {
        counts,
        symbols: Cow::Borrowed(&FIXED_LIT_SYMBOLS),
        fast: DecodeTable::Fixed(&FIXED_LIT_TABLE),
    }
}

pub fn fixed_dist() -> HuffmanTable {
    let mut counts = [0; MAX_CODE_LEN + 1];
    counts[5] = 32;
    HuffmanTable {
        counts,
        symbols: Cow::Borrowed(&FIXED_DIST_SYMBOLS),
        fast: DecodeTable::Fixed(&FIXED_DIST_TABLE),
    }
}

#[cfg(test)]
mod reuse_tests {
    use super::*;

    #[test]
    fn rebuild_reuses_allocations_and_clears_every_stale_entry() {
        let mut table = HuffmanTable::from_lengths(&[8; 256], Completeness::Complete).unwrap();
        let fast = table.fast_table().as_ptr();
        let symbols = table.symbols.as_ptr();
        for (lengths, completeness) in [
            (alloc::vec![1, 1], Completeness::Complete),
            (alloc::vec![], Completeness::AllowDegenerate),
            (alloc::vec![15], Completeness::AllowDegenerate),
            (alloc::vec![8; 256], Completeness::Complete),
            (alloc::vec![1], Completeness::AllowDegenerate),
        ] {
            assert!(table.rebuild(&[1, 1, 1], Completeness::Complete).is_err());
            table.rebuild(&lengths, completeness).unwrap();
            assert_eq!(
                table,
                HuffmanTable::from_lengths(&lengths, completeness).unwrap()
            );
            assert_eq!(table.fast_table().as_ptr(), fast);
            assert_eq!(table.symbols.as_ptr(), symbols);
        }
    }
}
