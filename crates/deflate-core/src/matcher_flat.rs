//! Retained trigram matcher for flat byte samples. The dual-index matcher
//! regressed those inputs. This keeps the preceding 128-probe search and
//! insertion policy; every winner passes the shared `matcher::accept`.

use crate::tokens::Token;
use alloc::vec;
use alloc::vec::Vec;

const WINDOW: usize = 32768;
const MIN_MATCH: usize = 3;
const MAX_MATCH: usize = 258;
const HASH_BITS: u32 = 15;
const MAX_CHAIN: usize = 128;

use crate::matcher::accept;

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
        // Small advances dominate text and random data; keep their short
        // scalar path and amortize batch setup only across longer matches.
        if end.saturating_sub(self.next_ins) < 16 {
            while self.next_ins < end {
                self.insert(self.next_ins);
                self.next_ins = self.next_ins.saturating_add(1);
            }
            return;
        }
        // Bound the whole run once: every window has three bytes and every
        // stored position fits u32. The scalar reference checks each position.
        let start = self.next_ins;
        let valid_end = end
            .min(self.input.len().saturating_sub(MIN_MATCH - 1))
            .min(u32::MAX as usize);
        if start < valid_end {
            let bytes = &self.input[start..valid_end + MIN_MATCH - 1];
            for (offset, bytes) in bytes.windows(MIN_MATCH).enumerate() {
                let p = start + offset;
                let h = hash(bytes[0], bytes[1], bytes[2]);
                if let (Some(hd), Some(pv)) = (self.head.get_mut(h), self.prev.get_mut(p % WINDOW))
                {
                    *pv = *hd;
                    *hd = (p + 1) as u32;
                }
            }
        }
        self.next_ins = self.next_ins.max(end);
    }

    /// Best verified `(len, dist)` at `i`, walking at most `MAX_CHAIN` links.
    fn find_best(&self, i: usize) -> Option<(usize, usize)> {
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
            // An older candidate must be strictly longer to replace best.
            // Reject it before scanning when that next byte already differs.
            if best.is_none_or(|(len, _)| self.input.get(c + len) == self.input.get(i + len)) {
                let len = self.common(c, i, limit);
                if len >= MIN_MATCH && best.is_none_or(|(bl, _)| len > bl) {
                    best = Some((len, dist));
                    if len >= limit {
                        break;
                    }
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
        let limit = limit.min(a.len()).min(b.len());
        let mut n = 0;
        // Hash collisions usually differ immediately. Avoid word loads for
        // them; only compare chunks after the three-byte prefix matches.
        while n < MIN_MATCH.min(limit) {
            if a[n] != b[n] {
                return n;
            }
            n += 1;
        }
        while n + 8 <= limit {
            let mut aw = [0; 8];
            let mut bw = [0; 8];
            aw.copy_from_slice(&a[n..n + 8]);
            bw.copy_from_slice(&b[n..n + 8]);
            let diff = u64::from_le_bytes(aw) ^ u64::from_le_bytes(bw);
            if diff != 0 {
                // Little-endian conversion makes this portable on every host.
                return n + diff.trailing_zeros() as usize / 8;
            }
            n += 8;
        }
        n + a[n..limit]
            .iter()
            .zip(&b[n..limit])
            .take_while(|(x, y)| x == y)
            .count()
    }

    /// Lazy matching needs only the existence of a better next match, not
    /// its maximum length. Check just the prefix that would beat current.
    fn better_next(&self, len: usize, dist: usize) -> bool {
        let i = self.i + 1;
        let limit = MAX_MATCH.min(self.input.len().saturating_sub(i));
        if limit < len || (len == MAX_MATCH && dist == 1) {
            return false;
        }
        let Some(h) = self.hash_at(i) else {
            return false;
        };
        let mut cand = self.head[h] as usize;
        for _ in 0..MAX_CHAIN {
            let Some(c) = cand.checked_sub(1) else { break };
            if c >= i || i - c > WINDOW {
                break;
            }
            let next_dist = i - c;
            let required = if next_dist < dist { len } else { len + 1 };
            if required > limit {
                // Older candidates are farther away, so cannot qualify either.
                break;
            }
            if self.input.get(c + required - 1) == self.input.get(i + required - 1)
                && accept(self.input, i, required, next_dist)
            {
                return true;
            }
            cand = self.prev[c % WINDOW] as usize;
        }
        false
    }
}

impl Iterator for Matcher<'_> {
    type Item = Token;

    fn next(&mut self) -> Option<Token> {
        let i = self.i;
        let byte = *self.input.get(i)?;

        // Ensure the hash tables are populated up to current position
        self.insert_up_to(i);

        // Find best match at current position
        let current = self.find_best(i);

        // Lazy matching: check if next position has a better match
        if let Some((len, dist)) = current {
            if self.better_next(len, dist) {
                // Emit literal instead, advance by 1
                self.i = i.saturating_add(1);
                return Some(Token::Literal(byte));
            }
            // Emit the match
            self.i = i.saturating_add(len);
            if let (Ok(l), Ok(d)) = (u16::try_from(len), u16::try_from(dist)) {
                return Some(Token::Match { len: l, dist: d });
            }
        }

        // No match or match not better than lookahead - emit literal
        self.i = i.saturating_add(1);
        Some(Token::Literal(byte))
    }
}

/// Lazy-match LZ77 tokens for `input` (Lean `compressTokens`). Memory is fixed
/// (about 256 KiB), independent of the input size.
pub(crate) fn tokens(input: &[u8]) -> impl Iterator<Item = Token> + '_ {
    Matcher {
        input,
        i: 0,
        next_ins: 0,
        head: vec![0; 1 << HASH_BITS],
        prev: vec![0; WINDOW],
    }
}
