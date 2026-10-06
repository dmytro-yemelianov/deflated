//! Dynamic-Huffman emitter, length heuristic wiring and block splitting
//! (M7b spec §2, §3.3, §3.4). Mirrors `spec/Deflate/EncodeDynamic.lean`.
//! `lengths_for` is an unproved heuristic; its output is always checked by
//! `valid_lengths` and the block falls back to fixed otherwise.

use crate::bitwriter::BitWriter;
use crate::block::CL_ORDER;
use crate::encode_fixed::{dist_sym, emit_fixed_block, length_sym};
use crate::huffman_build::{
    ClSym, UsedSymbols, build_lengths, canonical_codes, rle_lengths, valid_lengths,
};
use crate::lz77::{DIST_EXTRA, LENGTH_EXTRA};
use crate::tokens::Token;
use alloc::vec::Vec;

/// Tokens per block (spec §3.3).
pub const BLOCK_TOKENS: usize = 16384;

/// Lit, dist and CL code lengths (CL indexed by CL symbol 0..=18).
pub type Lengths = (Vec<u8>, Vec<u8>, Vec<u8>);

fn trim(ls: &mut Vec<u8>, min: usize) {
    let n = ls.iter().rposition(|&l| l != 0).map_or(0, |i| i + 1);
    ls.truncate(n.max(min));
}

/// Symbol frequencies of one block: lit/len (end of block, 256, counted
/// once) and distance. Everything `emit_block` decides (the lengths, the
/// used set, both bit sizes) is derived from these, so each block's tokens
/// are walked once for analysis and once to emit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Freqs {
    pub lit: [u32; 286],
    pub dist: [u32; 30],
}

/// `f * n` as `usize`, saturating (only reachable past `u32::MAX` tokens).
fn mul(f: u32, n: usize) -> usize {
    (f as usize).saturating_mul(n)
}

impl Freqs {
    /// One pass over `tokens`. `length_sym` is at most 285 and `dist_sym`
    /// at most 29 for every `u16`, so no token is lost.
    pub fn from_tokens(tokens: &[Token]) -> Self {
        let mut f = Freqs {
            lit: [0; 286],
            dist: [0; 30],
        };
        if let Some(x) = f.lit.get_mut(256) {
            *x = 1;
        }
        for t in tokens {
            let (l, d) = match *t {
                Token::Literal(b) => (usize::from(b), None),
                Token::Match { len, dist } => (
                    usize::from(length_sym(len).0),
                    Some(usize::from(dist_sym(dist).0)),
                ),
            };
            if let Some(x) = f.lit.get_mut(l) {
                *x = x.saturating_add(1);
            }
            if let Some(x) = d.and_then(|d| f.dist.get_mut(d)) {
                *x = x.saturating_add(1);
            }
        }
        f
    }

    /// The symbols the block uses: those with a nonzero count (256 always).
    pub fn used(&self) -> UsedSymbols {
        let mut u = UsedSymbols::new();
        for (s, &n) in self.lit.iter().enumerate() {
            if n > 0 {
                u.mark_lit(s as u16);
            }
        }
        for (s, &n) in self.dist.iter().enumerate() {
            if n > 0 {
                u.mark_dist(s as u16);
            }
        }
        u
    }

    /// Extra bits of all length and distance codes: they depend on the
    /// symbol only.
    fn extra_bits(&self) -> usize {
        let le: usize = self
            .lit
            .iter()
            .skip(257)
            .zip(LENGTH_EXTRA.iter())
            .map(|(&f, &e)| mul(f, usize::from(e)))
            .sum();
        let de: usize = self
            .dist
            .iter()
            .zip(DIST_EXTRA.iter())
            .map(|(&f, &e)| mul(f, usize::from(e)))
            .sum();
        le + de
    }

    /// Exact bit size of a fixed block (Lean `fixedBits`): Σ freq·len plus
    /// extra bits.
    pub fn fixed_bits(&self) -> usize {
        let lit: usize = self
            .lit
            .iter()
            .enumerate()
            .map(|(s, &f)| mul(f, fixed_lit_len(s)))
            .sum();
        let dist: usize = self.dist.iter().map(|&f| mul(f, 5)).sum();
        3 + lit + dist + self.extra_bits()
    }

    /// Exact bit size of a dynamic block with these lengths (Lean
    /// `dynBits`): header, RLE, then Σ freq·len plus extra bits.
    pub fn dynamic_bits(&self, lit: &[u8], dist: &[u8], cl: &[u8]) -> usize {
        let at = |ls: &[u8], s: usize| usize::from(ls.get(s).copied().unwrap_or(0));
        let mut n = 3 + 14 + 3 * (hclen(cl) + 4);
        let mut all = lit.to_vec();
        all.extend_from_slice(dist);
        for s in rle_lengths(&all) {
            n += at(cl, usize::from(s.symbol())) + extra(s).1 as usize;
        }
        let l: usize = self
            .lit
            .iter()
            .enumerate()
            .map(|(s, &f)| mul(f, at(lit, s)))
            .sum();
        let d: usize = self
            .dist
            .iter()
            .enumerate()
            .map(|(s, &f)| mul(f, at(dist, s)))
            .sum();
        n + l + d + self.extra_bits()
    }
}

/// Fixed lit/len code length (RFC 1951 §3.2.6).
fn fixed_lit_len(s: usize) -> usize {
    match s {
        0..=143 => 8,
        144..=255 => 9,
        256..=279 => 7,
        _ => 8,
    }
}

/// Heuristic lengths for a block over `tokens`, trimmed, or `None` when no
/// valid dynamic code was found (the block is then fixed).
pub fn lengths_for(tokens: &[Token]) -> Option<Lengths> {
    lengths_for_freqs(&Freqs::from_tokens(tokens))
}

/// [`lengths_for`] from a block's frequencies.
pub fn lengths_for_freqs(f: &Freqs) -> Option<Lengths> {
    let matches = f.dist.iter().any(|&n| n > 0);
    let mut lit = build_lengths(&f.lit, 15);
    let mut dist = if matches {
        build_lengths(&f.dist, 15)
    } else {
        let mut d = alloc::vec![0u8; 30];
        if let Some(x) = d.first_mut() {
            *x = 1;
        }
        d
    };
    trim(&mut lit, 257);
    trim(&mut dist, 1);
    let mut all = lit.clone();
    all.extend_from_slice(&dist);
    let mut cf = [0u32; 19];
    for s in rle_lengths(&all) {
        if let Some(f) = cf.get_mut(usize::from(s.symbol())) {
            *f = f.saturating_add(1);
        }
    }
    let mut cl = build_lengths(&cf, 7);
    let used: Vec<usize> = (0..19)
        .filter(|&i| cf.get(i).copied().unwrap_or(0) > 0)
        .collect();
    if let [only] = used[..] {
        // A lone CL symbol is an incomplete code; add a second one.
        let other = usize::from(only == 0);
        if let Some(l) = cl.get_mut(other) {
            *l = 1;
        }
    }
    if valid_lengths(&lit, &dist, &cl, &f.used()) {
        Some((lit, dist, cl))
    } else {
        None
    }
}

fn len_at(codes: &[(u16, u8)], s: usize) -> (u32, u32) {
    codes
        .get(s)
        .map_or((0, 0), |&(c, l)| (u32::from(c), u32::from(l)))
}

fn hclen(cl: &[u8]) -> usize {
    let last = CL_ORDER
        .iter()
        .rposition(|&s| cl.get(s).copied().unwrap_or(0) != 0)
        .map_or(0, |i| i + 1);
    last.max(4) - 4
}

fn extra(s: ClSym) -> (u32, u32) {
    match s {
        ClSym::Len(_) => (0, 0),
        ClSym::Rep16(v) => (u32::from(v), 2),
        ClSym::Zeros17(v) => (u32::from(v), 3),
        ClSym::Zeros18(v) => (u32::from(v), 7),
    }
}

/// Emit one dynamic block (Lean `emitDynamicBlock`). Callers pass trimmed,
/// valid lengths; nothing here is checked.
pub fn emit_dynamic_block(
    w: &mut BitWriter,
    final_: bool,
    lit: &[u8],
    dist: &[u8],
    cl: &[u8],
    tokens: &[Token],
) {
    w.write_bits(u32::from(final_), 1);
    w.write_bits(2, 2);
    w.write_bits(lit.len().saturating_sub(257) as u32, 5);
    w.write_bits(dist.len().saturating_sub(1) as u32, 5);
    let hc = hclen(cl);
    w.write_bits(hc as u32, 4);
    for &s in CL_ORDER.iter().take(hc + 4) {
        w.write_bits(u32::from(cl.get(s).copied().unwrap_or(0)), 3);
    }
    let clc = canonical_codes(cl);
    let mut all = lit.to_vec();
    all.extend_from_slice(dist);
    for s in rle_lengths(&all) {
        let (c, l) = len_at(&clc, usize::from(s.symbol()));
        w.write_code(c, l);
        let (v, n) = extra(s);
        w.write_bits(v, n);
    }
    let lc = canonical_codes(lit);
    let dc = canonical_codes(dist);
    for t in tokens {
        match *t {
            Token::Literal(b) => {
                let (c, l) = len_at(&lc, usize::from(b));
                w.write_code(c, l);
            }
            Token::Match { len, dist } => {
                let (ls, le, ln) = length_sym(len);
                let (c, l) = len_at(&lc, usize::from(ls));
                w.write_code(c, l);
                w.write_bits(le, ln);
                let (ds, de, dn) = dist_sym(dist);
                let (c, l) = len_at(&dc, usize::from(ds));
                w.write_code(c, l);
                w.write_bits(de, dn);
            }
        }
    }
    let (c, l) = len_at(&lc, 256);
    w.write_code(c, l);
}

/// Exact bit size of a fixed block over `tokens`.
pub fn fixed_bits(tokens: &[Token]) -> usize {
    Freqs::from_tokens(tokens).fixed_bits()
}

/// Exact bit size of a dynamic block with these lengths.
pub fn dynamic_bits(lit: &[u8], dist: &[u8], cl: &[u8], tokens: &[Token]) -> usize {
    Freqs::from_tokens(tokens).dynamic_bits(lit, dist, cl)
}

/// One block: dynamic iff `lengths_for` is valid and strictly smaller. One
/// analysis pass (`Freqs`), then the emit.
fn emit_block(w: &mut BitWriter, final_: bool, tokens: &[Token]) {
    let f = Freqs::from_tokens(tokens);
    if let Some((lit, dist, cl)) = lengths_for_freqs(&f)
        && f.dynamic_bits(&lit, &dist, &cl) < f.fixed_bits()
    {
        emit_dynamic_block(w, final_, &lit, &dist, &cl, tokens);
    } else {
        emit_fixed_block(w, final_, tokens.iter().copied());
    }
}

/// Choose a block token count from the next at most [`BLOCK_TOKENS`]
/// un-emitted tokens. The window is refilled before each call; only empty
/// input produces an empty window. Counts in `1..=BLOCK_TOKENS` are accepted
/// and capped to the remaining window length. `None`, zero and larger counts
/// use the default window length. Custom splitting is not covered by Lean's
/// default `emitBlocks` proof.
pub type SplitFor = fn(&[Token]) -> Option<usize>;

/// Block stream with bounded token lookahead: at most [`BLOCK_TOKENS`]
/// buffered tokens plus one token to determine finality. Output bytes grow
/// with the stream. Each nonempty block consumes at least one token.
pub fn emit_blocks_iter<I: Iterator<Item = Token>>(tokens: I, split_for: SplitFor) -> Vec<u8> {
    let mut tokens = tokens.fuse().peekable();
    let mut w = BitWriter::new();
    let mut chunk: Vec<Token> = Vec::with_capacity(BLOCK_TOKENS);
    loop {
        while chunk.len() < BLOCK_TOKENS {
            match tokens.next() {
                Some(t) => chunk.push(t),
                None => break,
            }
        }
        let bs = split_for(&chunk)
            .filter(|&n| (1..=BLOCK_TOKENS).contains(&n))
            .unwrap_or(BLOCK_TOKENS)
            .min(chunk.len());
        let last = bs == chunk.len() && tokens.peek().is_none();
        emit_block(&mut w, last, &chunk[..bs]);
        if last {
            return w.finish();
        }
        chunk.drain(..bs);
    }
}

/// Slice wrapper for [`emit_blocks_iter`]. With the default split this
/// mirrors Lean `emitBlocks`; custom split policies are checked in Rust.
pub fn emit_blocks(tokens: &[Token], split_for: SplitFor) -> Vec<u8> {
    emit_blocks_iter(tokens.iter().copied(), split_for)
}
