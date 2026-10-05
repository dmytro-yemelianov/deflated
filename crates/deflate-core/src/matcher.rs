//! Greedy hash-chain matcher (spec §3.2). Mirrors `spec/Deflate/Match.lean`
//! (`compressTokens`, `accept`). The finder is untrusted: every candidate
//! goes through `accept`, which is exactly the Lean acceptance rule.

use crate::tokens::Token;
use alloc::vec;
use alloc::vec::Vec;

const WINDOW: usize = 32768;
const MIN_MATCH: usize = 3;
const MAX_MATCH: usize = 258;
const HASH_BITS: u32 = 15;
const MAX_CHAIN: usize = 128;

/// Lean `accept`: the candidate `(len, dist)` at `i` is a legal match.
pub fn accept(input: &[u8], i: usize, len: usize, dist: usize) -> bool {
    if !(MIN_MATCH..=MAX_MATCH).contains(&len) || !(1..=WINDOW).contains(&dist) || dist > i {
        return false;
    }
    let end = match i.checked_add(len) {
        Some(e) if e <= input.len() => e,
        _ => return false,
    };
    // `dist <= i`, so the source starts at `i - dist` and never passes `i`.
    let src = i.saturating_sub(dist);
    match (
        input.get(i..end),
        input.get(src..end.min(src.saturating_add(len))),
    ) {
        (Some(a), Some(b)) => a == b,
        _ => false,
    }
}

fn hash(a: u8, b: u8, c: u8) -> usize {
    let v = (u32::from(a) << 16) | (u32::from(b) << 8) | u32::from(c);
    (v.wrapping_mul(0x9E37_79B1) >> (32 - HASH_BITS)) as usize
}

struct Matcher<'a> {
    input: &'a [u8],
    i: usize,
    /// Next position not yet inserted into the tables.
    next_ins: usize,
    /// Hash -> most recent position + 1 (0 = empty).
    head: Vec<u32>,
    /// Position mod WINDOW -> previous position with the same hash, + 1.
    prev: Vec<u32>,
}

impl Matcher<'_> {
    fn hash_at(&self, p: usize) -> Option<usize> {
        let w = self.input.get(p..p.checked_add(MIN_MATCH)?)?;
        match *w {
            [a, b, c] => Some(hash(a, b, c)),
            _ => None,
        }
    }

    fn insert(&mut self, p: usize) {
        let (Some(h), Ok(stored)) = (self.hash_at(p), u32::try_from(p.saturating_add(1))) else {
            return;
        };
        if let (Some(hd), Some(pv)) = (self.head.get_mut(h), self.prev.get_mut(p % WINDOW)) {
            *pv = *hd;
            *hd = stored;
        }
    }

    fn insert_up_to(&mut self, end: usize) {
        while self.next_ins < end {
            self.insert(self.next_ins);
            self.next_ins = self.next_ins.saturating_add(1);
        }
    }

    /// Best verified `(len, dist)` at `i`, walking at most `MAX_CHAIN` links.
    fn candidate(&self, i: usize) -> Option<(usize, usize)> {
        let h = self.hash_at(i)?;
        let limit = MAX_MATCH.min(self.input.len().saturating_sub(i));
        let mut cand = usize::try_from(*self.head.get(h)?).ok()?;
        let mut best: Option<(usize, usize)> = None;
        for _ in 0..MAX_CHAIN {
            let Some(c) = cand.checked_sub(1) else { break };
            if c >= i || i.saturating_sub(c) > WINDOW {
                break;
            }
            let dist = i.saturating_sub(c);
            let len = self.common(c, i, limit);
            if len >= MIN_MATCH && best.is_none_or(|(bl, _)| len > bl) {
                best = Some((len, dist));
                if len >= limit {
                    break;
                }
            }
            cand = usize::try_from(*self.prev.get(c % WINDOW)?).ok()?;
        }
        best.filter(|&(len, dist)| accept(self.input, i, len, dist))
    }

    /// Length of the common run of `input[c..]` and `input[i..]`, up to `limit`.
    fn common(&self, c: usize, i: usize, limit: usize) -> usize {
        let a = self.input.get(c..).unwrap_or_default();
        let b = self.input.get(i..).unwrap_or_default();
        a.iter()
            .zip(b.iter())
            .take(limit)
            .take_while(|(x, y)| x == y)
            .count()
    }
}

impl Iterator for Matcher<'_> {
    type Item = Token;

    fn next(&mut self) -> Option<Token> {
        let i = self.i;
        let byte = *self.input.get(i)?;
        self.insert_up_to(i);
        let found = self.candidate(i);
        if let Some((len, dist)) = found
            && let (Ok(l), Ok(d)) = (u16::try_from(len), u16::try_from(dist))
        {
            self.i = i.saturating_add(len);
            return Some(Token::Match { len: l, dist: d });
        }
        self.i = i.saturating_add(1);
        Some(Token::Literal(byte))
    }
}

/// Greedy LZ77 tokens for `input` (Lean `compressTokens`). Memory is fixed
/// (about 192 KiB), independent of the input size.
pub fn tokens(input: &[u8]) -> impl Iterator<Item = Token> + '_ {
    Matcher {
        input,
        i: 0,
        next_ins: 0,
        head: vec![0; 1 << HASH_BITS],
        prev: vec![0; WINDOW],
    }
}
