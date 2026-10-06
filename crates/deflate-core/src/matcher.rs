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
/// Search presets. Every emitted match still passes the Lean `accept` rule.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum CompressionLevel {
    /// Short search and greedy parsing for throughput.
    Fast,
    /// Lazy parsing with a bounded search for a speed/size compromise.
    #[default]
    Balanced,
    /// Deeper lazy search for smaller output, at a higher CPU cost.
    Best,
}

impl CompressionLevel {
    fn chain(self) -> usize {
        match self {
            Self::Fast => 4,
            Self::Balanced => 64,
            Self::Best => 512,
        }
    }
}

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

fn hash4(bytes: &[u8]) -> usize {
    let word = u32::from_le_bytes(bytes[..4].try_into().expect("four-byte prefix"));
    (word.wrapping_mul(0x1E35_A7BD) >> (32 - HASH_BITS)) as usize
}

// A flat byte sample favors the smaller trigram-only index. This selects a
// search heuristic, never a stored-output shortcut; matches remain checked.
fn flat_byte_sample(input: &[u8]) -> bool {
    if input.len() < 4096 {
        return false;
    }
    let mut counts = [0u16; 256];
    let step = (input.len() - 512) / 7;
    for sample in 0..8 {
        for &byte in &input[sample * step..sample * step + 512] {
            counts[usize::from(byte)] += 1;
            if counts[usize::from(byte)] > 64 {
                return false;
            }
        }
    }
    true
}

fn short_period_sample(input: &[u8]) -> bool {
    if input.len() < 4096 {
        return false;
    }
    let step = (input.len() - 512) / 7;
    (1..=16).any(|period| {
        (0..8).all(|sample| {
            let bytes = &input[sample * step..sample * step + 512];
            bytes[period..] == bytes[..512 - period]
        })
    })
}

pub(crate) fn use_flat_matcher(input: &[u8]) -> bool {
    !short_period_sample(input) && flat_byte_sample(input)
}

struct Chain {
    head: Vec<u32>,
    // Backward distances fit u16, including the full 32768-byte window.
    prev: Vec<u16>,
}

impl Chain {
    fn new() -> Self {
        Self {
            head: vec![0; 1 << HASH_BITS],
            prev: vec![0; WINDOW],
        }
    }

    fn insert(&mut self, p: usize, h: usize) {
        let Ok(stored) = u32::try_from(p + 1) else {
            return;
        };
        let prior = self.head[h] as usize;
        let distance = if prior > 0 { p + 1 - prior } else { 0 };
        self.prev[p % WINDOW] = if distance <= WINDOW {
            distance as u16
        } else {
            0
        };
        self.head[h] = stored;
    }

    // All these consecutive positions have the same hash. Keep the first
    // predecessor, then every following backward distance is exactly one.
    fn insert_run(&mut self, start: usize, end: usize, h: usize) {
        if start >= end {
            return;
        }
        self.insert(start, h);
        let count = end - start - 1;
        if count >= WINDOW {
            self.prev.fill(1);
        } else {
            let at = (start + 1) % WINDOW;
            let first = count.min(WINDOW - at);
            self.prev[at..at + first].fill(1);
            self.prev[..count - first].fill(1);
        }
        self.head[h] = end as u32;
    }

    fn insert_periodic(&mut self, start: usize, end: usize, hashes: &[usize]) {
        debug_assert!(end.saturating_sub(start) <= MAX_MATCH);
        let period = hashes.len();
        if end.saturating_sub(start) <= period {
            for p in start..end {
                self.insert(p, hashes[(p - start) % period]);
            }
            return;
        }
        // Insert the first cycle in chronological order, retaining its real
        // predecessors. Hash collisions between phases are included below.
        for (phase, &h) in hashes.iter().enumerate() {
            self.insert(start + phase, h);
        }
        for (phase, &h) in hashes.iter().enumerate() {
            let prior_phase = hashes[..phase]
                .iter()
                .rposition(|&x| x == h)
                .unwrap_or_else(|| hashes.iter().rposition(|&x| x == h).expect("own phase"));
            let delta = if prior_phase < phase {
                phase - prior_phase
            } else {
                period + phase - prior_phase
            };
            let mut last = start + phase;
            for p in (start + period + phase..end).step_by(period) {
                self.prev[p % WINDOW] = delta as u16;
                last = p;
            }
            self.head[h] = self.head[h].max((last + 1) as u32);
        }
    }

    fn candidates(&self, i: usize, h: usize, probes: usize) -> impl Iterator<Item = usize> + '_ {
        let mut candidate = (self.head[h] as usize).checked_sub(1);
        (0..probes).map_while(move |_| {
            let c = candidate?;
            if c >= i || i - c > WINDOW {
                return None;
            }
            let delta = self.prev[c % WINDOW] as usize;
            candidate = if delta == 0 {
                None
            } else {
                c.checked_sub(delta)
            };
            Some(c)
        })
    }
}

struct Matcher<'a> {
    input: &'a [u8],
    i: usize,
    next_ins: usize,
    short: Chain,
    long: Chain,
    level: CompressionLevel,
    three_only: bool,
    pending: Option<(usize, usize, usize)>,
}

impl<'a> Matcher<'a> {
    fn new(input: &'a [u8], level: CompressionLevel) -> Self {
        let three_only = level == CompressionLevel::Balanced
            && (short_period_sample(input) || flat_byte_sample(input));
        Self {
            input,
            i: 0,
            next_ins: 0,
            short: Chain::new(),
            long: if three_only {
                Chain {
                    head: Vec::new(),
                    prev: Vec::new(),
                }
            } else {
                Chain::new()
            },
            level,
            three_only,
            pending: None,
        }
    }

    #[cfg(test)]
    fn insert(&mut self, p: usize) {
        let Some(bytes) = self.input.get(p..) else {
            return;
        };
        if bytes.len() >= MIN_MATCH && p < u32::MAX as usize {
            self.short.insert(p, hash(bytes[0], bytes[1], bytes[2]));
            if !self.three_only && bytes.len() >= 4 {
                self.long.insert(p, hash4(bytes));
            }
        }
    }

    fn insert_up_to(&mut self, end: usize) {
        // Bounding the entire advance avoids per-byte range construction.
        let valid_end = end
            .min(self.input.len().saturating_sub(MIN_MATCH - 1))
            .min(u32::MAX as usize);
        let mut start = self.next_ins;
        if self.level == CompressionLevel::Fast && valid_end.saturating_sub(start) > 20 {
            // Fast retains a match's start and trailing positions instead of
            // indexing its entire interior. Literal runs still index every
            // byte. This deliberately trades search coverage for throughput.
            let bytes = &self.input[start..];
            self.short.insert(start, hash(bytes[0], bytes[1], bytes[2]));
            if !self.three_only && bytes.len() >= 4 {
                self.long.insert(start, hash4(bytes));
            }
            start = valid_end - 16;
        } else if valid_end.saturating_sub(start) >= 16 {
            let check_end = (valid_end + 3).min(self.input.len());
            let bytes = &self.input[start..check_end];
            let word = [bytes[0]; 8];
            let mut chunks = bytes.chunks_exact(8);
            if chunks.by_ref().all(|b| b == word)
                && chunks.remainder().iter().all(|&b| b == word[0])
            {
                self.short
                    .insert_run(start, valid_end, hash(word[0], word[0], word[0]));
                let long_end = valid_end.min(self.input.len().saturating_sub(3));
                if !self.three_only {
                    self.long.insert_run(start, long_end, hash4(&word));
                }
                self.next_ins = self.next_ins.max(end);
                return;
            }
        }
        if self.level != CompressionLevel::Fast {
            if let Some((match_start, match_end, period)) = self.pending.take() {
                if start == match_start && end == match_end && period <= 16 && end - start >= 32 {
                    // `accept` checked the preceding match. Overlap therefore
                    // makes this interior periodic; exclude the trailing
                    // positions whose hash reaches beyond that checked run.
                    let short_end = valid_end.min(end - 2);
                    let long_end = valid_end
                        .min(end - 3)
                        .min(self.input.len().saturating_sub(3));
                    let mut short_hashes = [0; 16];
                    let mut long_hashes = [0; 16];
                    for phase in 0..period {
                        let bytes = &self.input[start + phase..];
                        short_hashes[phase] = hash(bytes[0], bytes[1], bytes[2]);
                        if !self.three_only {
                            long_hashes[phase] = hash4(bytes);
                        }
                    }
                    self.short
                        .insert_periodic(start, short_end, &short_hashes[..period]);
                    if !self.three_only {
                        self.long
                            .insert_periodic(start, long_end, &long_hashes[..period]);
                    }
                    for p in long_end..valid_end {
                        let bytes = &self.input[p..];
                        if p >= short_end {
                            self.short.insert(p, hash(bytes[0], bytes[1], bytes[2]));
                        }
                        if !self.three_only && bytes.len() >= 4 {
                            self.long.insert(p, hash4(bytes));
                        }
                    }
                    self.next_ins = self.next_ins.max(end);
                    return;
                }
            }
        }
        for p in start..valid_end {
            let bytes = &self.input[p..];
            self.short.insert(p, hash(bytes[0], bytes[1], bytes[2]));
            if !self.three_only && bytes.len() >= 4 {
                self.long.insert(p, hash4(bytes));
            }
        }
        self.next_ins = self.next_ins.max(end);
    }

    /// Search four-byte chains for long matches; use the separate trigram
    /// chain when no longer match was found, preserving short-match coverage.
    fn find_best(&self, i: usize) -> Option<(usize, usize)> {
        let bytes = self.input.get(i..)?;
        let limit = MAX_MATCH.min(bytes.len());
        if limit < MIN_MATCH {
            return None;
        }
        let mut best = None;
        if self.three_only {
            let h = hash(bytes[0], bytes[1], bytes[2]);
            for c in self.short.candidates(i, h, 128) {
                if best.is_none_or(|(len, _)| self.input[c + len] == bytes[len]) {
                    let len = self.common(c, i, limit);
                    if len >= MIN_MATCH && best.is_none_or(|(bl, _)| len > bl) {
                        best = Some((len, i - c));
                        if len == limit {
                            break;
                        }
                    }
                }
            }
            return best.filter(|&(len, dist)| accept(self.input, i, len, dist));
        }
        if limit >= 4 {
            for c in self.long.candidates(i, hash4(bytes), self.level.chain()) {
                if best.is_none_or(|(len, _)| self.input[c + len] == bytes[len]) {
                    let len = self.common(c, i, limit);
                    if len >= 4 && best.is_none_or(|(bl, _)| len > bl) {
                        best = Some((len, i - c));
                        if len == limit {
                            break;
                        }
                    }
                }
            }
        }
        if best.is_none() {
            let h = hash(bytes[0], bytes[1], bytes[2]);
            for c in self.short.candidates(i, h, self.level.chain()) {
                if self.input[c..c + MIN_MATCH] == bytes[..MIN_MATCH] {
                    best = Some((MIN_MATCH, i - c));
                    break;
                }
            }
        }
        best.filter(|&(len, dist)| accept(self.input, i, len, dist))
    }

    /// Length of the common run of `input[c..]` and `input[i..]`, up to `limit`.
    fn common(&self, c: usize, i: usize, limit: usize) -> usize {
        let a = self.input.get(c..).unwrap_or_default();
        let b = self.input.get(i..).unwrap_or_default();
        let limit = limit.min(a.len()).min(b.len());
        let mut n = 0;
        if self.three_only {
            while n < MIN_MATCH.min(limit) {
                if a[n] != b[n] {
                    return n;
                }
                n += 1;
            }
        }
        for (aw, bw) in a[n..limit].chunks_exact(8).zip(b[n..limit].chunks_exact(8)) {
            let aw: [u8; 8] = aw.try_into().expect("eight-byte chunk");
            let bw: [u8; 8] = bw.try_into().expect("eight-byte chunk");
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
        let bytes = &self.input[i..];
        let limit = MAX_MATCH.min(bytes.len());
        if limit < len || (len == MAX_MATCH && dist == 1) {
            return false;
        }
        if self.three_only {
            let h = hash(bytes[0], bytes[1], bytes[2]);
            for c in self.short.candidates(i, h, 128) {
                let next_dist = i - c;
                let required = if next_dist < dist { len } else { len + 1 };
                if required > limit {
                    break;
                }
                if self.input[c + required - 1] == bytes[required - 1]
                    && accept(self.input, i, required, next_dist)
                {
                    return true;
                }
            }
            return false;
        }
        if len == MIN_MATCH {
            let h = hash(bytes[0], bytes[1], bytes[2]);
            for c in self.short.candidates(i, h, self.level.chain()) {
                if i - c >= dist {
                    break;
                }
                if accept(self.input, i, len, i - c) {
                    return true;
                }
            }
        }
        if limit < 4 {
            return false;
        }
        for c in self.long.candidates(i, hash4(bytes), self.level.chain()) {
            let next_dist = i - c;
            let required = 4.max(if next_dist < dist { len } else { len + 1 });
            if required > limit {
                break;
            }
            if self.input[c + required - 1] == bytes[required - 1]
                && accept(self.input, i, required, next_dist)
            {
                return true;
            }
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
            if self.level != CompressionLevel::Fast && self.better_next(len, dist) {
                // Emit literal instead, advance by 1
                self.i = i.saturating_add(1);
                self.pending = None;
                return Some(Token::Literal(byte));
            }
            // Emit the match
            self.i = i.saturating_add(len);
            self.pending = Some((i, self.i, dist));
            if let (Ok(l), Ok(d)) = (u16::try_from(len), u16::try_from(dist)) {
                return Some(Token::Match { len: l, dist: d });
            }
        }

        // No match or match not better than lookahead - emit literal
        self.i = i.saturating_add(1);
        self.pending = None;
        Some(Token::Literal(byte))
    }
}

/// Lazy-match LZ77 tokens for `input` (Lean `compressTokens`). Memory is fixed
/// (about 192–384 KiB), independent of the input size.
pub fn tokens(input: &[u8]) -> impl Iterator<Item = Token> + '_ {
    tokens_with_level(input, CompressionLevel::Balanced)
}

/// Tokens with a search preset. The finder is an untrusted heuristic;
/// candidates are checked by `accept` for every preset.
pub fn tokens_with_level(
    input: &[u8],
    level: CompressionLevel,
) -> impl Iterator<Item = Token> + '_ {
    Matcher::new(input, level)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tokens::Token;

    fn matcher(input: &[u8]) -> Matcher<'_> {
        Matcher::new(input, CompressionLevel::Balanced)
    }

    // Full byte-by-byte scoring over the preset's candidate sets, independent
    // of the optimized comparison and lazy threshold paths.
    fn reference_find(m: &Matcher<'_>, i: usize) -> Option<(usize, usize)> {
        let bytes = m.input.get(i..)?;
        let limit = MAX_MATCH.min(bytes.len());
        if limit < MIN_MATCH {
            return None;
        }
        let mut best = None;
        if m.three_only {
            let h = hash(bytes[0], bytes[1], bytes[2]);
            for c in m.short.candidates(i, h, 128) {
                let len = m.input[c..]
                    .iter()
                    .zip(bytes)
                    .take(limit)
                    .take_while(|(a, b)| a == b)
                    .count();
                if len >= MIN_MATCH && best.is_none_or(|(bl, _)| len > bl) {
                    best = Some((len, i - c));
                    if len == limit {
                        break;
                    }
                }
            }
            return best;
        }
        if limit >= 4 {
            for c in m.long.candidates(i, hash4(bytes), m.level.chain()) {
                let len = m.input[c..]
                    .iter()
                    .zip(bytes)
                    .take(limit)
                    .take_while(|(a, b)| a == b)
                    .count();
                if len >= 4 && best.is_none_or(|(bl, _)| len > bl) {
                    best = Some((len, i - c));
                    if len == limit {
                        break;
                    }
                }
            }
        }
        if best.is_none() {
            for c in m
                .short
                .candidates(i, hash(bytes[0], bytes[1], bytes[2]), m.level.chain())
            {
                if accept(m.input, i, MIN_MATCH, i - c) {
                    return Some((MIN_MATCH, i - c));
                }
            }
        }
        best
    }

    fn reference_tokens(input: &[u8], level: CompressionLevel) -> Vec<Token> {
        let mut m = Matcher::new(input, level);
        let mut out = Vec::new();
        while m.i < input.len() {
            let valid_end =
                m.i.min(input.len().saturating_sub(MIN_MATCH - 1))
                    .min(u32::MAX as usize);
            if level == CompressionLevel::Fast && valid_end.saturating_sub(m.next_ins) > 20 {
                m.insert(m.next_ins);
                m.next_ins = valid_end - 16;
            }
            while m.next_ins < m.i {
                m.insert(m.next_ins);
                m.next_ins += 1;
            }
            let current = reference_find(&m, m.i);
            if let Some((len, dist)) = current {
                if level == CompressionLevel::Fast
                    || !Matcher::is_better(current, reference_find(&m, m.i + 1))
                {
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
    fn presets_match_scalar_search_and_emit_only_accepted_tokens() {
        let mut seed = 0x1234_5678u32;
        let mut inputs = Vec::new();
        for alphabet in [4, 16, 256] {
            inputs.push(
                (0..2 * WINDOW + MAX_MATCH)
                    .map(|_| {
                        seed ^= seed << 13;
                        seed ^= seed >> 17;
                        seed ^= seed << 5;
                        (seed % alphabet) as u8
                    })
                    .collect::<Vec<_>>(),
            );
        }
        for period in [1, 2, 3, 7, 8, 9, 257, 258] {
            inputs.push(
                (0..2 * WINDOW + MAX_MATCH)
                    .map(|i| (i % period) as u8)
                    .collect(),
            );
        }
        for len in 0..=2 * MAX_MATCH {
            inputs.push(vec![42; len]);
        }
        for input in inputs {
            for level in [
                CompressionLevel::Fast,
                CompressionLevel::Balanced,
                CompressionLevel::Best,
            ] {
                let actual: Vec<_> = tokens_with_level(&input, level).collect();
                assert_eq!(actual, reference_tokens(&input, level), "{level:?}");
                let mut cursor = 0;
                for token in actual {
                    match token {
                        Token::Literal(b) => {
                            assert_eq!(b, input[cursor]);
                            cursor += 1;
                        }
                        Token::Match { len, dist } => {
                            assert!(accept(&input, cursor, usize::from(len), usize::from(dist)));
                            cursor += usize::from(len);
                        }
                    }
                }
                assert_eq!(cursor, input.len());
            }
        }
    }

    #[test]
    fn compact_links_preserve_absolute_chains_across_window_wrap() {
        let mut chain = Chain::new();
        let mut head = vec![0usize; 1 << HASH_BITS];
        let mut prev = vec![0usize; WINDOW];
        for p in 0..3 * WINDOW + 258 {
            let h = ((p * 31) ^ (p / 17)) % 193;
            if p % 257 == 0 || p % WINDOW <= 1 {
                let mut expected = Vec::new();
                let mut stored = head[h];
                for _ in 0..512 {
                    let Some(c) = stored.checked_sub(1) else {
                        break;
                    };
                    if c >= p || p - c > WINDOW {
                        break;
                    }
                    expected.push(c);
                    stored = prev[c % WINDOW];
                }
                assert_eq!(chain.candidates(p, h, 512).collect::<Vec<_>>(), expected);
            }
            prev[p % WINDOW] = head[h];
            head[h] = p + 1;
            chain.insert(p, h);
        }
        // A predecessor exactly one window back must not become the empty
        // sentinel; the next link outside that window must terminate.
        let mut chain = Chain::new();
        chain.insert(0, 1);
        assert_eq!(chain.candidates(WINDOW, 1, 4).collect::<Vec<_>>(), vec![0]);
        chain.insert(WINDOW, 1);
        assert_eq!(chain.candidates(WINDOW, 1, 4).collect::<Vec<_>>(), vec![]);
        assert_eq!(
            chain.candidates(WINDOW + 1, 1, 4).collect::<Vec<_>>(),
            vec![WINDOW]
        );
        assert_eq!(chain.prev[0], WINDOW as u16);
    }

    #[test]
    fn periodic_insertion_preserves_collision_links_and_window_wrap() {
        for hashes in [
            &[1][..],
            &[1, 1, 1],
            &[1, 2, 1, 3, 1],
            &[1, 2, 3, 1, 2, 4, 1, 2, 3],
        ] {
            for start in [0, 1, WINDOW - 10, WINDOW + 9] {
                for len in [
                    0,
                    1,
                    hashes.len() - 1,
                    hashes.len(),
                    hashes.len() + 1,
                    32,
                    MAX_MATCH,
                ] {
                    let mut bulk = Chain::new();
                    let mut scalar = Chain::new();
                    for p in 0..start {
                        let h = p % 13;
                        bulk.insert(p, h);
                        scalar.insert(p, h);
                    }
                    bulk.insert_periodic(start, start + len, hashes);
                    for p in start..start + len {
                        scalar.insert(p, hashes[(p - start) % hashes.len()]);
                    }
                    assert_eq!(bulk.head, scalar.head, "heads: {start} {len} {hashes:?}");
                    assert_eq!(bulk.prev, scalar.prev, "links: {start} {len} {hashes:?}");
                }
            }
        }
    }

    #[test]
    fn flat_sample_selects_smaller_index_without_skipping_compression() {
        let flat: Vec<_> = (0..8192).map(|i| i as u8).collect();
        assert!(flat_byte_sample(&flat));
        assert!(!flat_byte_sample(&vec![7; 8192]));
        assert!(!flat_byte_sample(&flat[..4095]));
        let m = Matcher::new(&flat, CompressionLevel::Balanced);
        assert!(m.three_only && m.long.head.is_empty() && m.long.prev.is_empty());
        // Flat byte frequencies can still be strongly compressible.
        assert!(tokens(&flat).any(|t| matches!(t, Token::Match { len, .. } if len > 3)));
        assert!(!Matcher::new(&flat, CompressionLevel::Best).three_only);
        assert!(use_flat_matcher(&flat));
        assert_eq!(
            tokens(&flat).collect::<Vec<_>>(),
            crate::matcher_flat::tokens(&flat).collect::<Vec<_>>()
        );
        let periodic: Vec<_> = (0..8192).map(|i| b"abcabcabd"[i % 9]).collect();
        assert!(short_period_sample(&periodic));
        assert!(!use_flat_matcher(&periodic));
        assert!(Matcher::new(&periodic, CompressionLevel::Balanced).three_only);
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
        let varied: Vec<u8> = (0..2 * WINDOW + MAX_MATCH)
            .map(|i| ((i * 31) ^ (i / 17)) as u8)
            .collect();
        for input in [varied, vec![7; 2 * WINDOW + MAX_MATCH]] {
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
                assert_eq!(bulk.short.head, scalar.short.head, "short heads at {end}");
                assert_eq!(bulk.long.head, scalar.long.head, "long heads at {end}");
                assert_eq!(bulk.short.prev, scalar.short.prev, "short links at {end}");
                assert_eq!(bulk.long.prev, scalar.long.prev, "long links at {end}");
                assert_eq!(bulk.next_ins, scalar.next_ins, "cursor at {end}");
            }
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
