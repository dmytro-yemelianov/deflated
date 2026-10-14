//! Private block-decoder tables. The public canonical/table API stays intact.
//! Entries carry symbol, base, extra-bit count and code-bit count together.
use crate::bitstream::BitReader;
use crate::error::Error;
use crate::huffman::{Completeness, MAX_CODE_LEN, prepare};
use crate::lz77::{DIST_BASE, DIST_EXTRA, LENGTH_BASE, LENGTH_EXTRA};
use alloc::{borrow::Cow, boxed::Box, vec::Vec};

// [value:16 | end:1 | literal:1 | index:5 | code bits:4 | total bits:5].
// Total bits include the extra length/distance bits, putting the next table
// lookup on a shorter dependency chain. Zero is a miss or reserved symbol.
pub(crate) const LITERAL: u32 = 1 << 14;
pub(crate) const END: u32 = 1 << 15;

pub(crate) const fn action(symbol: u16, bits: u32, distance: bool) -> u32 {
    let (base, extra, index, flags) = if distance {
        if symbol >= 30 {
            return 0;
        }
        (
            DIST_BASE[symbol as usize],
            DIST_EXTRA[symbol as usize],
            symbol,
            0,
        )
    } else if symbol < 256 {
        (symbol, 0, 0, LITERAL)
    } else if symbol == 256 {
        (0, 0, 0, END)
    } else if symbol <= 285 {
        let index = symbol as usize - 257;
        (LENGTH_BASE[index], LENGTH_EXTRA[index], index as u16, 0)
    } else {
        return 0;
    };
    (base as u32) << 16 | flags | (index as u32) << 9 | bits << 5 | (bits + extra as u32)
}

#[inline(always)]
pub(crate) fn match_value(entry: u32, word: u64) -> usize {
    (entry >> 16) as usize + ((word & ((1 << (entry & 31)) - 1)) >> ((entry >> 5) & 15)) as usize
}

pub(crate) trait TokenTable {
    const BITS: u32;
    fn lookup(&self, word: u64) -> u32;
    fn decode_symbol(&self, reader: &mut BitReader<'_>) -> Result<u16, Error>;
}

#[derive(Debug)]
pub(crate) struct PackedTable<const N: usize, const DISTANCE: bool> {
    counts: [u16; MAX_CODE_LEN + 1],
    symbols: Cow<'static, [u16]>,
    fast: Lookup<N>,
}

#[derive(Debug)]
enum Lookup<const N: usize> {
    Fixed(&'static [u32; N]),
    Built(Box<[u32; N]>),
}

impl<const N: usize> Lookup<N> {
    fn entries(&self) -> &[u32; N] {
        match self {
            Self::Fixed(table) => table,
            Self::Built(table) => table,
        }
    }
    fn entries_mut(&mut self) -> &mut [u32; N] {
        if let Self::Fixed(table) = self {
            *self = Self::Built(Box::new(**table));
        }
        match self {
            Self::Built(table) => table,
            Self::Fixed(_) => unreachable!(),
        }
    }
}

impl<const N: usize, const DISTANCE: bool> PackedTable<N, DISTANCE> {
    pub(crate) fn from_lengths(lengths: &[u8], completeness: Completeness) -> Result<Self, Error> {
        let mut symbols = Vec::new();
        let counts = prepare(lengths, completeness, &mut symbols)?;
        let mut table = Self {
            counts,
            symbols: Cow::Owned(symbols),
            fast: Lookup::Built(Box::new([0; N])),
        };
        table.build();
        Ok(table)
    }

    pub(crate) fn rebuild(
        &mut self,
        lengths: &[u8],
        completeness: Completeness,
    ) -> Result<(), Error> {
        self.counts = prepare(lengths, completeness, self.symbols.to_mut())?;
        self.build();
        Ok(())
    }

    fn build(&mut self) {
        // Root widths are private power-of-two constants: 7, 9 and 12 bits.
        let fast = self.fast.entries_mut();
        fast[..2].fill(0);
        let mut first = 0u32;
        let mut index = 0;
        for bits in 1..=Self::BITS {
            let count = self.counts[bits as usize];
            for i in 0..count {
                let symbol = self.symbols[index + usize::from(i)];
                let slot = (first + u32::from(i)).reverse_bits() >> (32 - bits);
                fast[slot as usize] = action(symbol, bits, DISTANCE);
            }
            index += usize::from(count);
            first = (first + u32::from(count)) << 1;
            if bits < Self::BITS {
                let filled = 1 << bits;
                fast.copy_within(..filled, filled);
            }
        }
    }
}

impl<const N: usize, const DISTANCE: bool> TokenTable for PackedTable<N, DISTANCE> {
    const BITS: u32 = N.trailing_zeros();
    #[inline(always)]
    fn lookup(&self, word: u64) -> u32 {
        self.fast.entries()[(word & (N as u64 - 1)) as usize]
    }
    #[inline]
    fn decode_symbol(&self, reader: &mut BitReader<'_>) -> Result<u16, Error> {
        if let Ok(word) = reader.peek_bits(Self::BITS) {
            let entry = self.lookup(u64::from(word));
            if entry != 0 {
                reader.skip_bits(((entry >> 5) & 15) as usize);
                return Ok(if entry & LITERAL != 0 {
                    (entry >> 16) as u16
                } else if entry & END != 0 {
                    256
                } else {
                    ((entry >> 9) & 31) as u16 + if DISTANCE { 0 } else { 257 }
                });
            }
        }
        crate::huffman::decode_canonical(&self.counts, &self.symbols, reader)
    }
}

pub(crate) type LitTable = PackedTable<4096, false>;
pub(crate) type DistTable = PackedTable<512, true>;
pub(crate) type CodeTable = PackedTable<128, false>;

const fn fixed<const N: usize>(distance: bool) -> [u32; N] {
    let mut fast = [0; N];
    let mut sym = 0;
    while sym < if distance { 32 } else { 288 } {
        let (code, bits): (u16, u32) = if distance {
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
        let mut slot = (code.reverse_bits() >> (16 - bits)) as usize;
        while slot < N {
            fast[slot] = action(sym, bits, distance);
            slot += 1 << bits;
        }
        sym += 1;
    }
    fast
}

static FIXED_LIT: [u32; 4096] = fixed(false);
static FIXED_DIST: [u32; 512] = fixed(true);

pub(crate) fn fixed_tables() -> (LitTable, DistTable) {
    // Reuse the canonical fixed symbol order and counts without allocating.
    let (lit_counts, lit_symbols) = crate::huffman::fixed_lit_parts();
    let (dist_counts, dist_symbols) = crate::huffman::fixed_dist_parts();
    (
        PackedTable {
            counts: lit_counts,
            symbols: Cow::Borrowed(lit_symbols),
            fast: Lookup::Fixed(&FIXED_LIT),
        },
        PackedTable {
            counts: dist_counts,
            symbols: Cow::Borrowed(dist_symbols),
            fast: Lookup::Fixed(&FIXED_DIST),
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::huffman::HuffmanTable;

    #[test]
    fn packed_match_actions_extract_every_extra_value() {
        for bits in 1..=15 {
            for distance in [false, true] {
                let (bases, extras): (&[u16], &[u8]) = if distance {
                    (&DIST_BASE, &DIST_EXTRA)
                } else {
                    (&LENGTH_BASE, &LENGTH_EXTRA)
                };
                for (index, (&base, &extra_bits)) in bases.iter().zip(extras).enumerate() {
                    let symbol = index as u16 + if distance { 0 } else { 257 };
                    let entry = action(symbol, bits, distance);
                    assert_eq!(entry & 31, bits + u32::from(extra_bits));
                    assert_eq!((entry >> 5) & 15, bits);
                    for extra in 0..1u64 << extra_bits {
                        // Code bits and following-token bits must not enter
                        // the match value. Expected values use the RFC arrays.
                        let word = (u64::MAX << (bits + u32::from(extra_bits)))
                            | (extra << bits)
                            | ((1 << bits) - 1);
                        assert_eq!(match_value(entry, word), usize::from(base) + extra as usize);
                    }
                }
            }
        }
        for symbol in [286, 287] {
            assert_eq!(action(symbol, 8, false), 0);
        }
        for symbol in [30, 31] {
            assert_eq!(action(symbol, 5, true), 0);
        }
    }

    fn compare<const N: usize, const DIST: bool>(lengths: &[u8], completeness: Completeness) {
        let table = PackedTable::<N, DIST>::from_lengths(lengths, completeness).unwrap();
        let canonical = HuffmanTable::from_lengths(lengths, completeness).unwrap();
        // Exhaust every root prefix, including misses and reserved symbols.
        for prefix in 0..N {
            let bytes = (prefix as u64).to_le_bytes();
            let mut reader = BitReader::new(&bytes);
            let symbol = canonical.decode(&mut reader);
            let expected = match symbol {
                Ok(symbol) if reader.bit_pos() <= PackedTable::<N, DIST>::BITS as usize => {
                    action(symbol, reader.bit_pos() as u32, DIST)
                }
                _ => 0,
            };
            assert_eq!(table.lookup(prefix as u64), expected);
        }
        let mut seed = 0x1951_1952_1234_5678u64;
        for _ in 0..128 {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            let bytes = seed.to_le_bytes();
            for end in 0..=bytes.len() {
                for offset in 0..8 {
                    let mut actual = BitReader::new(&bytes[..end]);
                    let mut reference = BitReader::new(&bytes[..end]);
                    actual.skip_bits(offset);
                    reference.skip_bits(offset);
                    assert_eq!(
                        table.decode_symbol(&mut actual),
                        canonical.decode(&mut reference)
                    );
                    assert_eq!(actual.bit_pos(), reference.bit_pos());
                }
            }
        }
    }

    #[test]
    fn action_tables_match_canonical_codes_and_error_cursors() {
        let mut comb = [0; 286];
        for (i, length) in comb.iter_mut().enumerate().take(14) {
            *length = i as u8 + 1;
        }
        comb[256] = 15;
        comb[285] = 15;
        compare::<4096, false>(&comb, Completeness::Complete);
        compare::<4096, false>(&[8; 256], Completeness::Complete);
        compare::<128, false>(
            &[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15],
            Completeness::Complete,
        );
        compare::<512, true>(&[5; 32], Completeness::Complete);
        for bits in 0..=15 {
            let mut lengths = [0; 30];
            lengths[29] = bits;
            compare::<512, true>(&lengths, Completeness::AllowDegenerate);
        }
    }

    #[test]
    fn packed_rebuild_clears_stale_entries_and_retains_allocations() {
        let mut table = LitTable::from_lengths(&[8; 256], Completeness::Complete).unwrap();
        let fast = table.fast.entries().as_ptr();
        let symbols = table.symbols.as_ptr();
        for (lengths, completeness) in [
            (alloc::vec![1, 1], Completeness::Complete),
            (alloc::vec![], Completeness::AllowDegenerate),
            (alloc::vec![15], Completeness::AllowDegenerate),
            (alloc::vec![8; 256], Completeness::Complete),
        ] {
            assert!(table.rebuild(&[1, 1, 1], Completeness::Complete).is_err());
            table.rebuild(&lengths, completeness).unwrap();
            let rebuilt = LitTable::from_lengths(&lengths, completeness).unwrap();
            assert_eq!(table.fast.entries(), rebuilt.fast.entries());
            assert_eq!(table.fast.entries().as_ptr(), fast);
            assert_eq!(table.symbols.as_ptr(), symbols);
        }
    }

    #[test]
    fn fixed_packed_tables_match_runtime_builders() {
        let (lit, dist) = fixed_tables();
        let mut lengths = [0; 288];
        lengths[..144].fill(8);
        lengths[144..256].fill(9);
        lengths[256..280].fill(7);
        lengths[280..].fill(8);
        assert_eq!(
            lit.fast.entries(),
            LitTable::from_lengths(&lengths, Completeness::Complete)
                .unwrap()
                .fast
                .entries()
        );
        assert_eq!(
            dist.fast.entries(),
            DistTable::from_lengths(&[5; 32], Completeness::Complete)
                .unwrap()
                .fast
                .entries()
        );
    }
}
