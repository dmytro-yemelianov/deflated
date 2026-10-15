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
// A root entry for codes longer than the root width: END with index 31, which
// no end-of-block action carries. Value is the subtable offset, code bits the
// root width and total bits the subtable width. Checked only after END.
const SUBTABLE: u32 = END | 31 << 9;

#[inline(always)]
pub(crate) fn is_subtable(entry: u32) -> bool {
    entry & SUBTABLE == SUBTABLE
}

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
    /// Root width.
    const BITS: u32;
    /// Longest code that `lookup_full` resolves; `BITS` without subtables.
    const MAX_BITS: u32;
    /// Root entry: an action, a miss (zero) or a subtable pointer.
    fn lookup(&self, word: u64) -> u32;
    /// The action addressed by a subtable pointer and the same `word`.
    fn resolve(&self, entry: u32, word: u64) -> u32;
    #[inline(always)]
    fn lookup_full(&self, word: u64) -> u32 {
        let entry = self.lookup(word);
        if Self::MAX_BITS > Self::BITS && is_subtable(entry) {
            self.resolve(entry, word)
        } else {
            entry
        }
    }
    fn decode_symbol(&self, reader: &mut BitReader<'_>) -> Result<u16, Error>;
}

#[derive(Debug)]
pub(crate) struct PackedTable<const N: usize, const DISTANCE: bool, const SUB: bool = false> {
    counts: [u16; MAX_CODE_LEN + 1],
    symbols: Cow<'static, [u16]>,
    fast: Lookup<N>,
    // Second-level entries for codes longer than the root (SUB only).
    sub: Vec<u32>,
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

impl<const N: usize, const DISTANCE: bool, const SUB: bool> PackedTable<N, DISTANCE, SUB> {
    pub(crate) fn from_lengths(lengths: &[u8], completeness: Completeness) -> Result<Self, Error> {
        let mut symbols = Vec::new();
        let counts = prepare(lengths, completeness, &mut symbols)?;
        let mut table = Self {
            counts,
            symbols: Cow::Owned(symbols),
            fast: Lookup::Built(Box::new([0; N])),
            sub: Vec::new(),
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
        // Root widths are private power-of-two constants: 7, 9 and 11 bits.
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
        self.sub.clear();
        if !SUB {
            return;
        }
        // Canonical codes sharing their first BITS bits are contiguous and
        // non-decreasing in length, so each prefix's last code is its longest.
        let root = Self::BITS;
        let mut widest = [0u8; N];
        let mut code = first;
        for bits in root + 1..=MAX_CODE_LEN as u32 {
            let count = u32::from(self.counts[bits as usize]);
            for c in code..code + count {
                widest[(c >> (bits - root)) as usize] = (bits - root) as u8;
            }
            code = (code + count) << 1;
        }
        let mut current = usize::MAX;
        let mut base = 0;
        for bits in root + 1..=MAX_CODE_LEN as u32 {
            let count = self.counts[bits as usize];
            for i in 0..count {
                let c = first + u32::from(i);
                let prefix = (c >> (bits - root)) as usize;
                let width = u32::from(widest[prefix]);
                if prefix != current {
                    current = prefix;
                    base = self.sub.len();
                    self.sub.resize(base + (1 << width), 0);
                    let slot = (prefix as u32).reverse_bits() >> (32 - root);
                    fast[slot as usize] = (base as u32) << 16 | SUBTABLE | root << 5 | width;
                }
                let rest = bits - root;
                let symbol = self.symbols[index + usize::from(i)];
                let entry = action(symbol, bits, DISTANCE);
                let mut slot = ((c & ((1 << rest) - 1)).reverse_bits() >> (32 - rest)) as usize;
                while slot < 1 << width {
                    self.sub[base + slot] = entry;
                    slot += 1 << rest;
                }
            }
            index += usize::from(count);
            first = (first + u32::from(count)) << 1;
        }
    }
}

impl<const N: usize, const DISTANCE: bool, const SUB: bool> TokenTable
    for PackedTable<N, DISTANCE, SUB>
{
    const BITS: u32 = N.trailing_zeros();
    const MAX_BITS: u32 = if SUB { MAX_CODE_LEN as u32 } else { Self::BITS };
    #[inline(always)]
    fn lookup(&self, word: u64) -> u32 {
        self.fast.entries()[(word & (N as u64 - 1)) as usize]
    }
    #[inline]
    fn resolve(&self, entry: u32, word: u64) -> u32 {
        let index = (word >> Self::BITS) & ((1 << (entry & 31)) - 1);
        let index = (entry >> 16) as usize + index as usize;
        self.sub.get(index).copied().unwrap_or(0)
    }
    #[inline]
    fn decode_symbol(&self, reader: &mut BitReader<'_>) -> Result<u16, Error> {
        if let Ok(word) = reader.peek_bits(Self::BITS) {
            let entry = self.lookup(u64::from(word));
            if entry != 0 && !(SUB && is_subtable(entry)) {
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

pub(crate) type LitTable = PackedTable<2048, false, true>;
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

static FIXED_LIT: [u32; 2048] = fixed(false);
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
            sub: Vec::new(),
        },
        PackedTable {
            counts: dist_counts,
            symbols: Cow::Borrowed(dist_symbols),
            fast: Lookup::Fixed(&FIXED_DIST),
            sub: Vec::new(),
        },
    )
}

#[cfg(test)]
pub(crate) mod tests {
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

    fn compare<const N: usize, const DIST: bool, const SUB: bool>(
        lengths: &[u8],
        completeness: Completeness,
    ) {
        let table = PackedTable::<N, DIST, SUB>::from_lengths(lengths, completeness).unwrap();
        let canonical = HuffmanTable::from_lengths(lengths, completeness).unwrap();
        let max = PackedTable::<N, DIST, SUB>::MAX_BITS;
        // Exhaust every prefix the tables can resolve, including subtable
        // codes, misses and reserved symbols. Bits above it must not matter.
        for prefix in 0..1u64 << max {
            let bytes = prefix.to_le_bytes();
            let mut reader = BitReader::new(&bytes);
            let symbol = canonical.decode(&mut reader);
            let expected = match symbol {
                Ok(symbol) if reader.bit_pos() <= max as usize => {
                    action(symbol, reader.bit_pos() as u32, DIST)
                }
                _ => 0,
            };
            assert_eq!(table.lookup_full(prefix), expected, "prefix={prefix:#x}");
            assert_eq!(table.lookup_full(prefix | u64::MAX << max), expected);
            if !SUB {
                assert!(!is_subtable(table.lookup(prefix)));
            }
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
        compare::<2048, false, true>(&comb, Completeness::Complete);
        compare::<2048, false, true>(&[8; 256], Completeness::Complete);
        for seed in 1..=24 {
            compare::<2048, false, true>(
                &random_complete_lengths(seed, 286),
                Completeness::Complete,
            );
        }
        compare::<128, false, false>(
            &[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15],
            Completeness::Complete,
        );
        compare::<512, true, false>(&[5; 32], Completeness::Complete);
        for bits in 0..=15 {
            let mut lengths = [0; 30];
            lengths[29] = bits;
            compare::<512, true, false>(&lengths, Completeness::AllowDegenerate);
        }
    }

    /// A complete code with many 12..15-bit codes: split random leaves of a
    /// one-leaf tree (preserving completeness), then shuffle the lengths.
    pub(crate) fn random_complete_lengths(mut seed: u64, symbols: usize) -> alloc::vec::Vec<u8> {
        let mut next = move || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        let mut leaves = alloc::vec![1u8, 1];
        while leaves.len() < symbols {
            // Favor the deepest splittable leaves to produce long codes.
            let pick = leaves.len() - 1 - (next() as usize % leaves.len().min(4));
            let i = if leaves[pick] < 15 {
                pick
            } else {
                match leaves.iter().position(|&l| l < 15) {
                    Some(i) => i,
                    None => break,
                }
            };
            leaves[i] += 1;
            let length = leaves[i];
            leaves.push(length);
        }
        for i in (1..leaves.len()).rev() {
            leaves.swap(i, next() as usize % (i + 1));
        }
        leaves
    }

    #[test]
    fn packed_rebuild_clears_stale_entries_and_retains_allocations() {
        // Start at the largest symbol count so retained capacity is observable.
        let start = random_complete_lengths(3, 286);
        let mut table = LitTable::from_lengths(&start, Completeness::Complete).unwrap();
        let fast = table.fast.entries().as_ptr();
        let symbols = table.symbols.as_ptr();
        for (lengths, completeness) in [
            (random_complete_lengths(7, 286), Completeness::Complete),
            (alloc::vec![1, 1], Completeness::Complete),
            (alloc::vec![], Completeness::AllowDegenerate),
            (alloc::vec![15], Completeness::AllowDegenerate),
            (alloc::vec![8; 256], Completeness::Complete),
        ] {
            assert!(table.rebuild(&[1, 1, 1], Completeness::Complete).is_err());
            table.rebuild(&lengths, completeness).unwrap();
            let rebuilt = LitTable::from_lengths(&lengths, completeness).unwrap();
            assert_eq!(table.fast.entries(), rebuilt.fast.entries());
            assert_eq!(table.sub, rebuilt.sub);
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
