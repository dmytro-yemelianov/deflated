//! P3 research parser. Bounded matching, one-step estimated-cost lookahead,
//! preceding-block Huffman feedback and at most one local refinement pass.
//! No optimality claim; actual rebuilt header/payload costs decide refinement.
use deflate_core::bitwriter::BitWriter;
use deflate_core::encode_dynamic::{
    BLOCK_TOKENS, Freqs, Lengths, emit_dynamic_block, lengths_for_freqs,
};
use deflate_core::encode_fixed::{dist_sym, emit_fixed_block, length_sym};
use deflate_core::tokens::Token;

const WINDOW: usize = 32768;
const MAX_MATCH: usize = 258;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Longest,
    Fixed,
    Feedback,
}

#[derive(Clone, Copy, Debug)]
pub struct Settings {
    pub probes: usize,
    pub lookahead: usize,
    pub mode: Mode,
    pub refine: bool,
}

impl Settings {
    pub fn parse(text: &str) -> Result<Self, String> {
        let fields: Vec<_> = text.split(':').collect();
        if fields.len() != 5 || fields[0] != "bounded" {
            return Err(
                "expected bounded:PROBES(4/8/16):LOOKAHEAD(0/1):longest|fixed|feedback:REFINE(0/1)"
                    .into(),
            );
        }
        let probes = fields[1].parse().map_err(|_| "invalid probes")?;
        let lookahead = fields[2].parse().map_err(|_| "invalid lookahead")?;
        let mode = match fields[3] {
            "longest" => Mode::Longest,
            "fixed" => Mode::Fixed,
            "feedback" => Mode::Feedback,
            _ => return Err("invalid cost mode".into()),
        };
        let refine = match fields[4] {
            "0" => false,
            "1" => true,
            _ => return Err("invalid refinement pass count".into()),
        };
        if ![4, 8, 16].contains(&probes) || lookahead > 1 || (refine && mode != Mode::Feedback) {
            return Err("unbounded or unsupported parser settings".into());
        }
        Ok(Self {
            probes,
            lookahead,
            mode,
            refine,
        })
    }
}

#[derive(Clone)]
struct Costs {
    lit: [u8; 256],
    len: [u16; 259],
    dist: [u8; 30],
}

impl Costs {
    fn fixed() -> Self {
        let mut result = Self {
            lit: [8; 256],
            len: [0; 259],
            dist: [5; 30],
        };
        result.lit[144..].fill(9);
        for len in 3..=MAX_MATCH {
            let (symbol, _, extra) = length_sym(len as u16);
            result.len[len] = (if symbol <= 279 { 7 } else { 8 }) + extra as u16;
        }
        result
    }

    fn from_lengths(lengths: &Lengths) -> Self {
        // Unseen symbols have no usable code in the previous block. Use 15
        // as a conservative estimate; every output block rebuilds valid codes.
        let at = |ls: &[u8], index| ls.get(index).copied().filter(|&n| n != 0).unwrap_or(15);
        let mut result = Self::fixed();
        for (symbol, value) in result.lit.iter_mut().enumerate() {
            *value = at(&lengths.0, symbol);
        }
        for len in 3..=MAX_MATCH {
            let (symbol, _, extra) = length_sym(len as u16);
            result.len[len] = u16::from(at(&lengths.0, symbol as usize)) + extra as u16;
        }
        for (symbol, value) in result.dist.iter_mut().enumerate() {
            *value = at(&lengths.1, symbol);
        }
        result
    }

    fn match_bits(&self, len: usize, dist: usize) -> u16 {
        let (symbol, _, extra) = dist_sym(dist as u16);
        self.len[len] + u16::from(self.dist[symbol as usize]) + extra as u16
    }

    fn token_bits(&self, token: Token) -> u16 {
        match token {
            Token::Literal(byte) => u16::from(self.lit[byte as usize]),
            Token::Match { len, dist } => self.match_bits(len as usize, dist as usize),
        }
    }
}

#[derive(Default, Debug)]
pub struct Stats {
    pub candidate_visits: usize,
    pub comparison_bytes_examined: usize,
    pub insertions: usize,
    pub lookahead_queries: usize,
    pub rejected_unprofitable: usize,
    pub tokens: usize,
    pub blocks: usize,
    pub huffman_analyses: usize,
    pub refinement_blocks_kept: usize,
    pub estimated_payload_bits: usize,
    pub actual_payload_bits: usize,
    pub header_and_eob_bits: usize,
    pub attempted_stream_bits: usize,
    pub stored_selected: bool,
}

fn hash(raw: &[u8], pos: usize) -> usize {
    let word =
        (u32::from(raw[pos]) << 16) | (u32::from(raw[pos + 1]) << 8) | u32::from(raw[pos + 2]);
    (word.wrapping_mul(0x9e37_79b1) >> 17) as usize
}

#[derive(Clone, Copy, Default)]
struct Choice {
    len: usize,
    dist: usize,
    gain: i32,
}

struct Parser<'a, const RECORD: bool> {
    raw: &'a [u8],
    settings: Settings,
    costs: Costs,
    head: Vec<u32>,
    prev: Vec<u16>,
    position: usize,
    indexed: usize,
    stats: Stats,
}

impl<'a, const RECORD: bool> Parser<'a, RECORD> {
    fn new(raw: &'a [u8], settings: Settings) -> Self {
        Self {
            raw,
            settings,
            costs: Costs::fixed(),
            head: vec![0; 1 << 15],
            prev: vec![0; WINDOW],
            position: 0,
            indexed: 0,
            stats: Stats::default(),
        }
    }

    fn insert_to(&mut self, end: usize) {
        let end = end
            .min(self.raw.len().saturating_sub(2))
            .min(u32::MAX as usize);
        while self.indexed < end {
            let pos = self.indexed;
            let slot = hash(self.raw, pos);
            self.prev[pos % WINDOW] = (self.head[slot] as usize)
                .checked_sub(1)
                .filter(|&p| p < pos && pos - p <= WINDOW)
                .map_or(0, |p| (pos - p) as u16);
            self.head[slot] = pos as u32 + 1;
            self.indexed += 1;
            if RECORD {
                self.stats.insertions += 1;
            }
        }
    }

    fn common(&mut self, pos: usize, previous: usize, limit: usize) -> usize {
        let mut len = 0;
        while len < 3.min(limit) {
            if RECORD {
                self.stats.comparison_bytes_examined += 1;
            }
            if self.raw[pos + len] != self.raw[previous + len] {
                return len;
            }
            len += 1;
        }
        while len + 8 <= limit {
            if RECORD {
                self.stats.comparison_bytes_examined += 8;
            }
            let a = u64::from_le_bytes(self.raw[pos + len..pos + len + 8].try_into().unwrap());
            let b = u64::from_le_bytes(
                self.raw[previous + len..previous + len + 8]
                    .try_into()
                    .unwrap(),
            );
            let diff = a ^ b;
            if diff != 0 {
                return len + diff.trailing_zeros() as usize / 8;
            }
            len += 8;
        }
        while len < limit {
            if RECORD {
                self.stats.comparison_bytes_examined += 1;
            }
            if self.raw[pos + len] != self.raw[previous + len] {
                break;
            }
            len += 1;
        }
        len
    }

    fn best(&mut self, pos: usize) -> Choice {
        let limit = MAX_MATCH.min(self.raw.len() - pos);
        if limit < 3 {
            return Choice::default();
        }
        let mut matches = [(0usize, 0usize); 16];
        let mut count = 0;
        let mut visited = 0;
        // The one-step query sees the pending literal as a virtual link.
        // It never mutates the dictionary used by the current position.
        for previous in self.position..pos {
            visited += 1;
            if RECORD {
                self.stats.candidate_visits += 1;
            }
            let len = self.common(pos, previous, limit);
            if len >= 3 {
                matches[count] = (len, pos - previous);
                count += 1;
            }
        }
        let slot = hash(self.raw, pos);
        let mut candidate = self.head[slot] as usize;
        while visited < self.settings.probes && candidate != 0 {
            let previous = candidate - 1;
            if previous >= pos || pos - previous > WINDOW {
                break;
            }
            visited += 1;
            if RECORD {
                self.stats.candidate_visits += 1;
            }
            let len = self.common(pos, previous, limit);
            if len >= 3 {
                matches[count] = (len, pos - previous);
                count += 1;
            }
            let delta = self.prev[previous % WINDOW] as usize;
            candidate = if delta != 0 && delta <= previous {
                candidate - delta
            } else {
                0
            };
            // With fixed codes, increasing length increases saved literal
            // bits, and later links cannot have a cheaper distance. Feedback
            // costs need not be monotone and retain the bounded alternatives.
            if self.settings.mode != Mode::Feedback && len == limit {
                break;
            }
        }
        if count == 0 {
            return Choice::default();
        }
        if self.settings.mode == Mode::Longest {
            let &(len, dist) = matches[..count]
                .iter()
                .max_by_key(|&&(len, dist)| (len, std::cmp::Reverse(dist)))
                .unwrap();
            return Choice {
                len,
                dist,
                gain: len as i32,
            };
        }
        let mut prefix = [0u16; MAX_MATCH + 1];
        let maximum = matches[..count].iter().map(|m| m.0).max().unwrap();
        for len in 1..=maximum {
            prefix[len] =
                prefix[len - 1] + u16::from(self.costs.lit[self.raw[pos + len - 1] as usize]);
        }
        let mut result = Choice::default();
        for &(len, dist) in &matches[..count] {
            // Bound alternative prefixes too; no all-length DP or input DAG.
            for (selected, &literal_bits) in prefix
                .iter()
                .enumerate()
                .take(len + 1)
                .skip(len.saturating_sub(self.settings.probes).max(3))
            {
                let gain =
                    i32::from(literal_bits) - i32::from(self.costs.match_bits(selected, dist));
                if (gain, selected, std::cmp::Reverse(dist))
                    > (result.gain, result.len, std::cmp::Reverse(result.dist))
                {
                    result = Choice {
                        len: selected,
                        dist,
                        gain,
                    };
                }
            }
        }
        if RECORD && result.len == 0 {
            self.stats.rejected_unprofitable += 1;
        }
        result
    }

    fn next(&mut self) -> Option<Token> {
        let pos = self.position;
        let byte = *self.raw.get(pos)?;
        self.insert_to(pos);
        let mut best = self.best(pos);
        if self.settings.lookahead != 0
            && best.len != 0
            && best.len < 32
            && pos + 1 < self.raw.len()
        {
            if RECORD {
                self.stats.lookahead_queries += 1;
            }
            let later = self.best(pos + 1);
            let threshold = if self.settings.mode == Mode::Longest {
                best.gain + 1
            } else {
                best.gain
            };
            if later.gain > threshold {
                best = Choice::default();
            }
        }
        let token = if best.len >= 3 {
            assert!(deflate_core::matcher::accept(
                self.raw, pos, best.len, best.dist
            ));
            self.position += best.len;
            Token::Match {
                len: best.len as u16,
                dist: best.dist as u16,
            }
        } else {
            self.position += 1;
            Token::Literal(byte)
        };
        Some(token)
    }
}

struct Prepared {
    lengths: Option<Lengths>,
    costs: Costs,
    bits: usize,
    payload: usize,
}

fn prepare(tokens: &[Token]) -> Prepared {
    let frequencies = Freqs::from_tokens(tokens);
    let lengths = lengths_for_freqs(&frequencies).filter(|(lit, dist, cl)| {
        frequencies.dynamic_bits(lit, dist, cl) < frequencies.fixed_bits()
    });
    let bits = lengths.as_ref().map_or_else(
        || frequencies.fixed_bits(),
        |(lit, dist, cl)| frequencies.dynamic_bits(lit, dist, cl),
    );
    let costs = lengths
        .as_ref()
        .map_or_else(Costs::fixed, Costs::from_lengths);
    let payload = tokens
        .iter()
        .map(|&t| usize::from(costs.token_bits(t)))
        .sum();
    Prepared {
        lengths,
        costs,
        bits,
        payload,
    }
}

fn refine(raw: &[u8], start: usize, tokens: &[Token], costs: &Costs, budget: usize) -> Vec<Token> {
    let mut result = Vec::with_capacity(BLOCK_TOKENS);
    let mut position = start;
    for (index, &token) in tokens.iter().enumerate() {
        let remaining = tokens.len() - index - 1;
        if let Token::Match { len, dist } = token {
            let len = len as usize;
            let original = costs.match_bits(len, dist as usize);
            let mut best = (original, len);
            let mut tail_bits = 0;
            for tail in 1..=budget.min(len) {
                tail_bits += u16::from(costs.lit[raw[position + len - tail] as usize]);
                let prefix = len - tail;
                if prefix < 3 && prefix != 0 {
                    continue;
                }
                let count = tail + usize::from(prefix != 0);
                if result.len() + count + remaining > BLOCK_TOKENS {
                    continue;
                }
                let bits = tail_bits
                    + if prefix == 0 {
                        0
                    } else {
                        costs.match_bits(prefix, dist as usize)
                    };
                if bits < best.0 {
                    best = (bits, prefix);
                }
            }
            if best.1 != 0 {
                result.push(Token::Match {
                    len: best.1 as u16,
                    dist,
                });
            }
            result.extend(
                raw[position + best.1..position + len]
                    .iter()
                    .copied()
                    .map(Token::Literal),
            );
            position += len;
        } else {
            result.push(token);
            position += 1;
        }
    }
    result
}

pub struct Output {
    pub packet: Vec<u8>,
    pub stats: Stats,
}

/// Whole-input token witnesses are restricted to short oracle diagnostics.
/// This allocation is outside native timing and absent from the encoder.
pub fn short_tokens(raw: &[u8], settings: Settings) -> Result<Vec<Token>, String> {
    if raw.len() > 4096 {
        return Err("short-token witness exceeds 4096 bytes".into());
    }
    let mut parser = Parser::<false>::new(raw, settings);
    let mut tokens = Vec::new();
    while let Some(token) = parser.next() {
        tokens.push(token);
    }
    if settings.refine {
        let before = prepare(&tokens);
        let refined = refine(raw, 0, &tokens, &before.costs, settings.probes);
        if prepare(&refined).bits < before.bits {
            tokens = refined;
        }
    }
    Ok(tokens)
}

pub fn encode<const RECORD: bool>(raw: &[u8], settings: Settings) -> Output {
    let mut parser = Parser::<RECORD>::new(raw, settings);
    let mut writer = BitWriter::new();
    let mut chunk = Vec::with_capacity(BLOCK_TOKENS);
    loop {
        chunk.clear();
        let start = parser.position;
        while chunk.len() < BLOCK_TOKENS {
            let Some(token) = parser.next() else {
                break;
            };
            chunk.push(token);
        }
        let mut analysis = prepare(&chunk);
        if RECORD {
            parser.stats.huffman_analyses += 1;
        }
        let mut refined = Vec::new();
        let mut selected = &chunk[..];
        if settings.refine {
            refined = refine(raw, start, &chunk, &analysis.costs, settings.probes);
            if refined != chunk {
                let alternative = prepare(&refined);
                if RECORD {
                    parser.stats.huffman_analyses += 1;
                }
                if alternative.bits < analysis.bits {
                    analysis = alternative;
                    selected = &refined;
                    if RECORD {
                        parser.stats.refinement_blocks_kept += 1;
                    }
                }
            }
        }
        if RECORD {
            parser.stats.tokens += selected.len();
            parser.stats.blocks += 1;
            parser.stats.estimated_payload_bits += selected
                .iter()
                .map(|&t| usize::from(parser.costs.token_bits(t)))
                .sum::<usize>();
            parser.stats.actual_payload_bits += analysis.payload;
            parser.stats.header_and_eob_bits += analysis.bits - analysis.payload;
        }
        let final_ = parser.position == raw.len();
        if let Some((lit, dist, cl)) = &analysis.lengths {
            emit_dynamic_block(&mut writer, final_, lit, dist, cl, selected);
        } else {
            emit_fixed_block(&mut writer, final_, selected.iter().copied());
        }
        if settings.mode == Mode::Feedback {
            parser.costs = analysis.costs;
        }
        // Keep the chosen buffer alive until emission is complete.
        drop(refined);
        if final_ {
            break;
        }
    }
    if RECORD {
        parser.stats.attempted_stream_bits = writer.bit_len();
    }
    let packet = writer.finish();
    let stored = raw
        .len()
        .saturating_add(raw.len().div_ceil(65535).max(1).saturating_mul(5));
    if packet.len() < stored {
        Output {
            packet,
            stats: parser.stats,
        }
    } else {
        parser.stats.stored_selected = true;
        Output {
            packet: deflate_core::deflate_stored(raw),
            stats: parser.stats,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepted_tokens_ring_wraps_and_exact_emission_accounting() {
        let mut word = 43_u32;
        let random: Vec<_> = (0..2 * WINDOW + 259)
            .map(|i| {
                word = word.wrapping_mul(1664525).wrapping_add(1013904223);
                if i % 4096 < 2048 {
                    (word >> 24) as u8
                } else {
                    b"abcab"[i % 5]
                }
            })
            .collect();
        for len in [
            0,
            1,
            2,
            3,
            257,
            258,
            259,
            WINDOW - 1,
            WINDOW + 1,
            random.len(),
        ] {
            let raw = &random[..len];
            for probes in [4, 8, 16] {
                for lookahead in [0, 1] {
                    for mode in [Mode::Longest, Mode::Fixed, Mode::Feedback] {
                        for refinement in [false, true] {
                            if refinement && mode != Mode::Feedback {
                                continue;
                            }
                            let settings = Settings {
                                probes,
                                lookahead,
                                mode,
                                refine: refinement,
                            };
                            let mut parser = Parser::<true>::new(raw, settings);
                            let mut tokens = Vec::new();
                            while let Some(t) = parser.next() {
                                tokens.push(t);
                            }
                            assert_eq!(deflate_core::tokens::expand(&tokens).unwrap(), raw);
                            let output = encode::<true>(raw, settings);
                            assert_eq!(output.packet, encode::<false>(raw, settings).packet);
                            assert_eq!(deflate_core::inflate(&output.packet).unwrap(), raw);
                            assert_eq!(
                                miniz_oxide::inflate::decompress_to_vec(&output.packet).unwrap(),
                                raw
                            );
                            assert_eq!(
                                output.stats.attempted_stream_bits,
                                output.stats.actual_payload_bits + output.stats.header_and_eob_bits
                            );
                            assert!(
                                output.stats.candidate_visits <= output.stats.tokens * probes * 2
                            );
                        }
                    }
                }
            }
        }
    }
    #[test]
    fn refinement_preserves_expansion_and_single_block_packet_size() {
        let raw = b"abcabcXabcabcYabcabcZabcdefabcdef";
        let settings = Settings {
            probes: 16,
            lookahead: 1,
            mode: Mode::Feedback,
            refine: false,
        };
        let mut parser = Parser::<false>::new(raw, settings);
        let mut tokens = Vec::new();
        while let Some(t) = parser.next() {
            tokens.push(t);
        }
        let before = prepare(&tokens);
        let refined = refine(raw, 0, &tokens, &before.costs, 16);
        assert_eq!(deflate_core::tokens::expand(&refined).unwrap(), raw);
        assert!(refined.len() <= BLOCK_TOKENS);
        let mut word = 43u32;
        for len in 0..256 {
            let raw: Vec<u8> = (0..len)
                .map(|_| {
                    word = word.wrapping_mul(1664525).wrapping_add(1013904223);
                    ((word >> 24) % 5) as u8
                })
                .collect();
            let original = encode::<true>(&raw, settings);
            let refined = encode::<true>(
                &raw,
                Settings {
                    refine: true,
                    ..settings
                },
            );
            // These short inputs fit one block: feedback cannot change any
            // later parse. Compare actual final padded packets, not estimates.
            assert!(refined.packet.len() <= original.packet.len());
            assert_eq!(deflate_core::inflate(&refined.packet).unwrap(), raw);
            assert!(refined.stats.refinement_blocks_kept <= 1);
            assert!(refined.stats.huffman_analyses <= 2);
        }
    }

    #[test]
    fn command_line_rejects_unbounded_or_unsupported_settings() {
        for text in [
            "bounded:17:0:fixed:0",
            "bounded:4:2:fixed:0",
            "bounded:4:0:feedback:2",
            "bounded:4:0:longest:1",
            "bounded:4:0:unknown:0",
            "bounded:4:0:fixed",
        ] {
            assert!(Settings::parse(text).is_err(), "{text}");
        }
    }
}
