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

/// Heuristic lengths for a block over `tokens`, trimmed, or `None` when no
/// valid dynamic code was found (the block is then fixed).
pub fn lengths_for(tokens: &[Token]) -> Option<Lengths> {
    let mut lf = [0u32; 286];
    let mut df = [0u32; 30];
    if let Some(f) = lf.get_mut(256) {
        *f = 1;
    }
    let mut matches = false;
    for t in tokens {
        match *t {
            Token::Literal(b) => {
                if let Some(f) = lf.get_mut(usize::from(b)) {
                    *f = f.saturating_add(1);
                }
            }
            Token::Match { len, dist } => {
                matches = true;
                if let Some(f) = lf.get_mut(usize::from(length_sym(len).0)) {
                    *f = f.saturating_add(1);
                }
                if let Some(f) = df.get_mut(usize::from(dist_sym(dist).0)) {
                    *f = f.saturating_add(1);
                }
            }
        }
    }
    let mut lit = build_lengths(&lf, 15);
    let mut dist = if matches {
        build_lengths(&df, 15)
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
    if valid_lengths(&lit, &dist, &cl, &UsedSymbols::from_tokens(tokens)) {
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
    let lit = |s: u16| match s {
        0..=143 => 8,
        144..=255 => 9,
        256..=279 => 7,
        _ => 8,
    };
    let mut n = 3 + lit(256);
    for t in tokens {
        n += match *t {
            Token::Literal(b) => lit(u16::from(b)),
            Token::Match { len, dist } => {
                let (ls, _, ln) = length_sym(len);
                let (_, _, dn) = dist_sym(dist);
                lit(ls) + ln as usize + 5 + dn as usize
            }
        };
    }
    n
}

/// Exact bit size of a dynamic block with these lengths.
pub fn dynamic_bits(lit: &[u8], dist: &[u8], cl: &[u8], tokens: &[Token]) -> usize {
    let at = |ls: &[u8], s: u16| usize::from(ls.get(usize::from(s)).copied().unwrap_or(0));
    let mut n = 3 + 14 + 3 * (hclen(cl) + 4);
    let mut all = lit.to_vec();
    all.extend_from_slice(dist);
    for s in rle_lengths(&all) {
        n += at(cl, u16::from(s.symbol())) + extra(s).1 as usize;
    }
    n += at(lit, 256);
    for t in tokens {
        n += match *t {
            Token::Literal(b) => at(lit, u16::from(b)),
            Token::Match { len, dist: d } => {
                let (ls, _, ln) = length_sym(len);
                let (ds, _, dn) = dist_sym(d);
                at(lit, ls) + ln as usize + at(dist, ds) + dn as usize
            }
        };
    }
    n
}

/// One block: dynamic iff `lengths_for` is valid and strictly smaller.
fn emit_block(w: &mut BitWriter, final_: bool, tokens: &[Token]) {
    if let Some((lit, dist, cl)) = lengths_for(tokens)
        && dynamic_bits(&lit, &dist, &cl, tokens) < fixed_bits(tokens)
    {
        emit_dynamic_block(w, final_, &lit, &dist, &cl, tokens);
    } else {
        emit_fixed_block(w, final_, tokens.iter().copied());
    }
}

/// Block stream over a token iterator, buffering one chunk at a time. The
/// last chunk (or the only, possibly empty, one) is final.
pub fn emit_blocks_iter<I: Iterator<Item = Token>>(mut tokens: I) -> Vec<u8> {
    let mut w = BitWriter::new();
    let mut chunk: Vec<Token> = Vec::with_capacity(BLOCK_TOKENS);
    let mut carry = tokens.next();
    loop {
        chunk.clear();
        while chunk.len() < BLOCK_TOKENS
            && let Some(t) = carry.take()
        {
            chunk.push(t);
            carry = tokens.next();
        }
        let last = carry.is_none();
        emit_block(&mut w, last, &chunk);
        if last {
            return w.finish();
        }
    }
}

/// Lean `emitBlocks` (with the Rust heuristic as `lengthsFor`).
pub fn emit_blocks(tokens: &[Token]) -> Vec<u8> {
    emit_blocks_iter(tokens.iter().copied())
}
