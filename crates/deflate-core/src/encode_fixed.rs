//! Fixed-Huffman emitter (spec §3.4). Mirrors `spec/Deflate/EncodeFixed.lean`.
//!
//! Layout: BFINAL=1, BTYPE=01, one symbol per token, symbol 256, zero pad.

use crate::bitwriter::BitWriter;
use crate::lz77::{DIST_BASE, DIST_EXTRA, LENGTH_BASE, LENGTH_EXTRA};
use crate::tokens::Token;
use alloc::vec::Vec;

/// Largest `i` with `base[i] <= v`; 0 if none (out-of-contract input).
/// Compile-time only: the tables below are built from it.
const fn slot(base: &[u16], v: usize) -> u8 {
    let mut i = 0;
    let mut s = 0;
    while i < base.len() {
        if base[i] as usize <= v {
            s = i;
        }
        i += 1;
    }
    s as u8
}

/// `LEN_SLOT[len]` is the length-code index for `len` in 0..=258.
const LEN_SLOT: [u8; 259] = {
    let mut t = [0u8; 259];
    let mut v = 0;
    while v < t.len() {
        t[v] = slot(&LENGTH_BASE, v);
        v += 1;
    }
    t
};

/// `DIST_LO[d]` is the distance-code index for `d` in 0..=256.
const DIST_LO: [u8; 257] = {
    let mut t = [0u8; 257];
    let mut v = 0;
    while v < t.len() {
        t[v] = slot(&DIST_BASE, v);
        v += 1;
    }
    t
};

/// `DIST_HI[(d - 1) >> 7]` is the distance-code index for `d >= 257`. Every
/// base from 257 up is `128k + 1`, so a bucket `128k+1 ..= 128k+128` never
/// straddles a base and one entry per bucket suffices (zlib's `_dist_code`
/// trick). 512 buckets cover all of `u16`.
const DIST_HI: [u8; 512] = {
    let mut t = [0u8; 512];
    let mut k = 0;
    while k < t.len() {
        t[k] = slot(&DIST_BASE, 128 * k + 1);
        k += 1;
    }
    t
};

/// Length-code index for any `u16`; lengths past 258 take the last code,
/// like the linear scan they replace.
fn len_slot(len: u16) -> usize {
    match LEN_SLOT.get(usize::from(len)) {
        Some(&i) => usize::from(i),
        None => LENGTH_BASE.len() - 1,
    }
}

/// Distance-code index for any `u16` (0 for distance 0).
fn dist_slot(dist: u16) -> usize {
    let d = usize::from(dist);
    let i = if d <= 256 {
        DIST_LO.get(d)
    } else {
        DIST_HI.get((d - 1) >> 7)
    };
    usize::from(i.copied().unwrap_or(0))
}

/// `(symbol, extra value, extra bit count)` for a match length 3..=258.
/// O(1): one table lookup.
pub fn length_sym(len: u16) -> (u16, u32, u32) {
    let i = len_slot(len);
    let base = LENGTH_BASE.get(i).copied().unwrap_or(0);
    let nb = LENGTH_EXTRA.get(i).copied().unwrap_or(0);
    (
        257 + i as u16,
        u32::from(len.saturating_sub(base)),
        u32::from(nb),
    )
}

/// `(symbol, extra value, extra bit count)` for a distance 1..=32768.
/// O(1): one table lookup.
pub fn dist_sym(dist: u16) -> (u16, u32, u32) {
    let i = dist_slot(dist);
    let base = DIST_BASE.get(i).copied().unwrap_or(0);
    let nb = DIST_EXTRA.get(i).copied().unwrap_or(0);
    (
        i as u16,
        u32::from(dist.saturating_sub(base)),
        u32::from(nb),
    )
}

/// Write a fixed lit/len symbol (RFC 1951 §3.2.6).
fn put_litlen(w: &mut BitWriter, sym: u16) {
    let s = u32::from(sym);
    match sym {
        0..=143 => w.write_code(0x30 + s, 8),
        144..=255 => w.write_code(0x190 + (s - 144), 9),
        256..=279 => w.write_code(s - 256, 7),
        _ => w.write_code(0xC0 + (s - 280), 8),
    }
}

/// Emit one fixed-Huffman block into `w` with the given BFINAL bit. Does not
/// pad, so blocks can share a writer.
pub fn emit_fixed_block<I: IntoIterator<Item = Token>>(w: &mut BitWriter, final_: bool, tokens: I) {
    w.write_bits(u32::from(final_), 1);
    w.write_bits(1, 2);
    for t in tokens {
        match t {
            Token::Literal(b) => put_litlen(w, u16::from(b)),
            Token::Match { len, dist } => {
                let (ls, le, ln) = length_sym(len);
                put_litlen(w, ls);
                w.write_bits(le, ln);
                let (ds, de, dn) = dist_sym(dist);
                w.write_code(u32::from(ds), 5);
                w.write_bits(de, dn);
            }
        }
    }
    put_litlen(w, 256);
}

/// Emit one final fixed-Huffman block (Lean `emitFixed`).
pub fn emit_fixed<I: IntoIterator<Item = Token>>(tokens: I) -> Vec<u8> {
    let mut w = BitWriter::new();
    emit_fixed_block(&mut w, true, tokens);
    w.finish()
}
