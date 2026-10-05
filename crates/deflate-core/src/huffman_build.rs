//! Encoder side of canonical Huffman codes (M7b spec §3.1, §3.2, §3.4).
//!
//! [`build_lengths`] is an unproved heuristic; everything it produces goes
//! through [`valid_lengths`], which mirrors Lean `validLengths`, before a
//! dynamic block is emitted. [`canonical_codes`] mirrors Lean
//! `canonicalCode` and [`rle_lengths`] mirrors `rleLengths`.

use crate::encode_fixed::{dist_sym, length_sym};
use crate::huffman::{Completeness, HuffmanTable};
use crate::tokens::Token;
use alloc::vec::Vec;

/// Which lit/len and distance symbols a block uses.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct UsedSymbols {
    lit: [u64; 5],
    dist: [u64; 1],
}

impl UsedSymbols {
    pub fn new() -> Self {
        Self::default()
    }

    /// Mark lit/len symbol `s` (0..=319); larger values are ignored.
    pub fn mark_lit(&mut self, s: u16) {
        if let Some(w) = self.lit.get_mut(usize::from(s >> 6)) {
            *w |= 1u64 << (s & 63);
        }
    }

    /// Mark distance symbol `s` (0..=63); larger values are ignored.
    pub fn mark_dist(&mut self, s: u16) {
        if let Some(w) = self.dist.get_mut(usize::from(s >> 6)) {
            *w |= 1u64 << (s & 63);
        }
    }

    pub fn lit(&self, s: u16) -> bool {
        self.lit
            .get(usize::from(s >> 6))
            .is_some_and(|w| (w >> (s & 63)) & 1 == 1)
    }

    pub fn dist(&self, s: u16) -> bool {
        self.dist
            .get(usize::from(s >> 6))
            .is_some_and(|w| (w >> (s & 63)) & 1 == 1)
    }

    /// Symbols a block over `tokens` needs: literals, length and distance
    /// symbols, and always 256 (end of block).
    pub fn from_tokens(tokens: &[Token]) -> Self {
        let mut u = Self::new();
        u.mark_lit(256);
        for t in tokens {
            match *t {
                Token::Literal(b) => u.mark_lit(u16::from(b)),
                Token::Match { len, dist } => {
                    u.mark_lit(length_sym(len).0);
                    u.mark_dist(dist_sym(dist).0);
                }
            }
        }
        u
    }
}

/// Length-limited code lengths for `freqs`; zero frequency gets length 0.
///
/// Huffman by two queues over frequency-sorted leaves, then overlong codes
/// are rebalanced miniz/zlib style. One used symbol gets length 1 (an
/// incomplete code; callers decide), none gives all zeros. If more than
/// `2^max_len` symbols are used, no code exists and the result is all zeros.
pub fn build_lengths(freqs: &[u32], max_len: u8) -> Vec<u8> {
    let mut out = alloc::vec![0u8; freqs.len()];
    let max = usize::from(max_len);
    let mut leaves: Vec<(u64, usize)> = freqs
        .iter()
        .enumerate()
        .filter(|&(_, &f)| f > 0)
        .map(|(s, &f)| (u64::from(f), s))
        .collect();
    let n = leaves.len();
    if n == 0 || max == 0 || max > 32 || n > (1usize << max.min(31)) {
        return out;
    }
    if n == 1 {
        if let Some(&(_, s)) = leaves.first()
            && let Some(o) = out.get_mut(s)
        {
            *o = 1;
        }
        return out;
    }
    leaves.sort_unstable();

    // Nodes 0..n are leaves in ascending weight; n.. are internal nodes,
    // created in non-decreasing weight order, so each queue stays sorted.
    let total = 2 * n - 1;
    let mut weight: Vec<u64> = leaves.iter().map(|&(w, _)| w).collect();
    let mut parent = alloc::vec![0usize; total];
    let (mut li, mut ii) = (0usize, n);
    for node in n..total {
        let mut sum = 0u64;
        for _ in 0..2 {
            let lw = if li < n {
                weight.get(li).copied()
            } else {
                None
            };
            let iw = if ii < node {
                weight.get(ii).copied()
            } else {
                None
            };
            let take_leaf = match (lw, iw) {
                (Some(a), Some(b)) => a <= b,
                (Some(_), None) => true,
                _ => false,
            };
            let child = if take_leaf {
                li += 1;
                li - 1
            } else {
                ii += 1;
                ii - 1
            };
            sum += weight.get(child).copied().unwrap_or(0);
            if let Some(p) = parent.get_mut(child) {
                *p = node;
            }
        }
        weight.push(sum);
    }

    // Depths, root down; counts per length with everything deeper than
    // `max` folded into `max`.
    let mut depth = alloc::vec![0usize; total];
    let mut num = alloc::vec![0u64; max + 1];
    for i in (0..total.saturating_sub(1)).rev() {
        let p = parent.get(i).copied().unwrap_or(0);
        let d = depth.get(p).copied().unwrap_or(0) + 1;
        if let Some(x) = depth.get_mut(i) {
            *x = d;
        }
        if i < n
            && let Some(c) = num.get_mut(d.min(max))
        {
            *c += 1;
        }
    }

    // Restore Kraft equality after clamping (miniz `enforce_max_code_size`).
    let mut kraft: u64 = 0;
    for (l, &c) in num.iter().enumerate().skip(1) {
        kraft += c << (max - l);
    }
    let target = 1u64 << max;
    while kraft > target {
        if let Some(c) = num.get_mut(max) {
            *c = c.saturating_sub(1);
        }
        for l in (1..max).rev() {
            if num.get(l).copied().unwrap_or(0) != 0 {
                if let Some(c) = num.get_mut(l) {
                    *c -= 1;
                }
                if let Some(c) = num.get_mut(l + 1) {
                    *c += 2;
                }
                break;
            }
        }
        kraft -= 1;
    }

    // Shortest codes to the heaviest leaves (descending weight = reverse of
    // the ascending leaf order).
    let mut idx = n;
    for l in 1..=max {
        for _ in 0..num.get(l).copied().unwrap_or(0) {
            idx = idx.saturating_sub(1);
            if let Some(&(_, s)) = leaves.get(idx)
                && let Some(o) = out.get_mut(s)
            {
                *o = l as u8;
            }
        }
    }
    out
}

/// Canonical `(code, length)` per symbol, RFC 1951 §3.2.2; `(0, 0)` for
/// unused symbols. Lean `canonicalCode`. Lengths above 15 are out of
/// contract and yield `(0, 0)`.
pub fn canonical_codes(lengths: &[u8]) -> Vec<(u16, u8)> {
    let mut bl_count = [0u32; 16];
    for &l in lengths {
        if l > 0
            && let Some(c) = bl_count.get_mut(usize::from(l))
        {
            *c += 1;
        }
    }
    let mut next_code = [0u32; 17];
    let mut code = 0u32;
    for bits in 1..=15usize {
        code = (code + bl_count.get(bits - 1).copied().unwrap_or(0)) << 1;
        if let Some(n) = next_code.get_mut(bits) {
            *n = code;
        }
    }
    lengths
        .iter()
        .map(|&l| {
            if l == 0 {
                return (0, 0);
            }
            match next_code.get_mut(usize::from(l)) {
                Some(n) if l <= 15 => {
                    let c = *n;
                    *n += 1;
                    (c as u16, l)
                }
                _ => (0, 0),
            }
        })
        .collect()
}

/// A code-length-alphabet symbol with its extra-bits value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClSym {
    /// Symbols 0..=15.
    Len(u8),
    /// Symbol 16: repeat previous, 3..=6 times; value is `count - 3` (2 bits).
    Rep16(u8),
    /// Symbol 17: zeros, 3..=10; value is `count - 3` (3 bits).
    Zeros17(u8),
    /// Symbol 18: zeros, 11..=138; value is `count - 11` (7 bits).
    Zeros18(u8),
}

impl ClSym {
    /// The CL alphabet symbol, 0..=18.
    pub fn symbol(self) -> u8 {
        match self {
            ClSym::Len(v) => v,
            ClSym::Rep16(_) => 16,
            ClSym::Zeros17(_) => 17,
            ClSym::Zeros18(_) => 18,
        }
    }
}

/// Run-length encode `lengths` (callers pass `lit ++ dist`). Lean `rleLengths`.
pub fn rle_lengths(lengths: &[u8]) -> Vec<ClSym> {
    let mut out = Vec::new();
    let mut i = 0;
    while let Some(&v) = lengths.get(i) {
        let mut n = lengths
            .get(i..)
            .map_or(0, |s| s.iter().take_while(|&&x| x == v).count());
        i += n;
        if v == 0 {
            while n >= 11 {
                let c = n.min(138);
                out.push(ClSym::Zeros18((c - 11) as u8));
                n -= c;
            }
            if n >= 3 {
                out.push(ClSym::Zeros17((n - 3) as u8));
                n = 0;
            }
            for _ in 0..n {
                out.push(ClSym::Len(0));
            }
        } else {
            out.push(ClSym::Len(v));
            n -= 1;
            while n >= 3 {
                let c = n.min(6);
                out.push(ClSym::Rep16((c - 3) as u8));
                n -= c;
            }
            for _ in 0..n {
                out.push(ClSym::Len(v));
            }
        }
    }
    out
}

/// Lean `validLengths`: whether a decoder accepts these three codes and
/// every symbol `used` (and every CL symbol the RLE needs) has a code.
pub fn valid_lengths(lit: &[u8], dist: &[u8], cl: &[u8], used: &UsedSymbols) -> bool {
    if !(257..=286).contains(&lit.len()) || !(1..=30).contains(&dist.len()) || cl.len() != 19 {
        return false;
    }
    if cl.iter().any(|&l| l > 7) {
        return false;
    }
    // `from_lengths` rejects lengths above 15 and checks Kraft.
    if HuffmanTable::from_lengths(lit, Completeness::Complete).is_err()
        || HuffmanTable::from_lengths(dist, Completeness::AllowDegenerate).is_err()
        || HuffmanTable::from_lengths(cl, Completeness::Complete).is_err()
    {
        return false;
    }
    for s in 0..320u16 {
        if used.lit(s) && lit.get(usize::from(s)).copied().unwrap_or(0) == 0 {
            return false;
        }
    }
    for s in 0..64u16 {
        if used.dist(s) && dist.get(usize::from(s)).copied().unwrap_or(0) == 0 {
            return false;
        }
    }
    let mut all = Vec::with_capacity(lit.len() + dist.len());
    all.extend_from_slice(lit);
    all.extend_from_slice(dist);
    rle_lengths(&all)
        .iter()
        .all(|s| cl.get(usize::from(s.symbol())).copied().unwrap_or(0) != 0)
}
