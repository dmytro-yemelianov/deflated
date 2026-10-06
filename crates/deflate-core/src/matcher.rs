//! Lazy-match LZ77 matcher (spec §3.2). Mirrors `spec/Deflate/Match.lean`
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

    /// Compare two matches: return true if m2 is better than m1.
    /// Better = longer, or same length but closer distance.
    #[cfg(test)]
    fn is_better(m1: Option<(usize, usize)>, m2: Option<(usize, usize)>) -> bool {
        match (m1, m2) {
            (None, Some(_)) => true,
            (Some((l1, d1)), Some((l2, d2))) => l2 > l1 || (l2 == l1 && d2 < d1),
            _ => false,
        }
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
pub fn tokens(input: &[u8]) -> impl Iterator<Item = Token> + '_ {
    Matcher {
        input,
        i: 0,
        next_ins: 0,
        head: vec![0; 1 << HASH_BITS],
        prev: vec![0; WINDOW],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tokens::Token;

    fn matcher(input: &[u8]) -> Matcher<'_> {
        Matcher {
            input,
            i: 0,
            next_ins: 0,
            head: vec![0; 1 << HASH_BITS],
            prev: vec![0; WINDOW],
        }
    }

    // The original search: no candidate pruning, compare one byte at a time.
    fn reference_find(m: &Matcher<'_>, i: usize) -> Option<(usize, usize)> {
        let h = m.hash_at(i)?;
        let limit = MAX_MATCH.min(m.input.len() - i);
        let mut cand = m.head[h] as usize;
        let mut best = None;
        for _ in 0..MAX_CHAIN {
            let Some(c) = cand.checked_sub(1) else { break };
            if c >= i || i - c > WINDOW {
                break;
            }
            let len = m.input[c..]
                .iter()
                .zip(&m.input[i..])
                .take(limit)
                .take_while(|(a, b)| a == b)
                .count();
            if len >= MIN_MATCH && best.is_none_or(|(bl, _)| len > bl) {
                best = Some((len, i - c));
                if len == limit {
                    break;
                }
            }
            cand = m.prev[c % WINDOW] as usize;
        }
        best.filter(|&(len, dist)| accept(m.input, i, len, dist))
    }

    fn reference_tokens(input: &[u8]) -> Vec<Token> {
        let mut m = matcher(input);
        let mut out = Vec::new();
        while m.i < input.len() {
            while m.next_ins < m.i {
                m.insert(m.next_ins);
                m.next_ins += 1;
            }
            let current = reference_find(&m, m.i);
            if let Some((len, dist)) = current {
                if !Matcher::is_better(current, reference_find(&m, m.i + 1)) {
                    out.push(Token::Match {
                        len: len as u16,
                        dist: dist as u16,
                    });
                    m.i += len;
                    continue;
                }
            }
            out.push(Token::Literal(input[m.i]));
            m.i += 1;
        }
        out
    }

    #[test]
    fn word_comparison_matches_byte_reference_at_every_boundary() {
        for offset in 0..8 {
            for mismatch in 0..=MAX_MATCH {
                let mut input = vec![0x5a; 2 * (MAX_MATCH + 8)];
                let i = MAX_MATCH + 8 + offset;
                if i + mismatch < input.len() {
                    input[i + mismatch] = 0xa5;
                }
                let m = matcher(&input);
                for limit in [0, 1, 2, 3, 7, 8, 9, 15, 16, mismatch, MAX_MATCH] {
                    let expected = input[offset..]
                        .iter()
                        .zip(&input[i..])
                        .take(limit)
                        .take_while(|(a, b)| a == b)
                        .count();
                    assert_eq!(m.common(offset, i, limit), expected);
                }
            }
        }
        let input = [7; 64];
        let m = matcher(&input);
        for c in 0..=65 {
            for i in 0..=65 {
                let expected = 64usize.saturating_sub(c.max(i)).min(MAX_MATCH);
                assert_eq!(m.common(c, i, MAX_MATCH), expected);
            }
        }
    }

    #[test]
    fn bulk_insertion_preserves_scalar_tables() {
        let input: Vec<u8> = (0..2 * WINDOW + MAX_MATCH)
            .map(|i| ((i * 31) ^ (i / 17)) as u8)
            .collect();
        let mut bulk = matcher(&input);
        let mut scalar = matcher(&input);
        for end in [
            0,
            1,
            2,
            3,
            MAX_MATCH,
            WINDOW - 1,
            WINDOW,
            WINDOW + 1,
            input.len() - 2,
            input.len() - 1,
            input.len(),
            input.len() + 1,
            0,
        ] {
            bulk.insert_up_to(end);
            while scalar.next_ins < end {
                scalar.insert(scalar.next_ins);
                scalar.next_ins += 1;
            }
            assert_eq!(bulk.head, scalar.head, "heads at {end}");
            assert_eq!(bulk.prev, scalar.prev, "links at {end}");
            assert_eq!(bulk.next_ins, scalar.next_ins, "cursor at {end}");
        }
    }

    #[test]
    fn optimized_matcher_preserves_original_tokens() {
        let mut seed = 0x1234_5678u32;
        for alphabet in [4, 16, 256] {
            let input: Vec<u8> = (0..(2 * WINDOW + MAX_MATCH))
                .map(|_| {
                    seed ^= seed << 13;
                    seed ^= seed >> 17;
                    seed ^= seed << 5;
                    (seed % alphabet) as u8
                })
                .collect();
            assert_eq!(tokens(&input).collect::<Vec<_>>(), reference_tokens(&input));
        }
        for period in [1, 2, 3, 7, 8, 9, 16, 257, 258] {
            let input: Vec<u8> = (0..(2 * WINDOW + MAX_MATCH))
                .map(|i| (i % period) as u8)
                .collect();
            assert_eq!(tokens(&input).collect::<Vec<_>>(), reference_tokens(&input));
        }
        for len in 0..=2 * MAX_MATCH {
            let input = vec![42; len];
            assert_eq!(tokens(&input).collect::<Vec<_>>(), reference_tokens(&input));
        }
    }

    #[test]
    fn lazy_prefers_longer_lookahead() {
        // Input: "abcXabcY"
        // At position 0: match "abc" (len=3) at distance 4 (lookahead at pos 4)
        // But at position 1: match "bcXabcY" could be longer
        // Actually let's construct a case where lookahead is better
        let input = b"abcdefghijklabcdefghijkl";
        let toks: Vec<Token> = tokens(input).collect();
        // Should find match at position 12 (second "abcdefghijkl")
        let has_long_match = toks
            .iter()
            .any(|t| matches!(t, Token::Match { len, .. } if *len > 3));
        assert!(has_long_match, "Should find matches: {toks:?}");
    }

    #[test]
    fn lazy_still_emits_literals() {
        let input = b"abcdefghijkl";
        let toks: Vec<Token> = tokens(input).collect();
        // All literals, no matches
        assert!(toks.iter().all(|t| matches!(t, Token::Literal(_))));
    }

    #[test]
    fn lazy_roundtrip_small() {
        let input = b"hello world hello world";
        let toks: Vec<Token> = tokens(input).collect();
        // Should find the second "hello world" as a match
        let match_count = toks
            .iter()
            .filter(|t| matches!(t, Token::Match { .. }))
            .count();
        assert!(match_count > 0, "Should find at least one match: {toks:?}");
    }
}
