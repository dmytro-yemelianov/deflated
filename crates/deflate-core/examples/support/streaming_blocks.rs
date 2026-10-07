//! P4 bounded streaming block spike. Greedy block choices are not globally
//! optimal. A single matcher retains dictionary history across every block.
use deflate_core::CompressionLevel;
use deflate_core::bitwriter::BitWriter;
use deflate_core::encode_dynamic::{Freqs, emit_dynamic_block, lengths_for_freqs};
use deflate_core::encode_fixed::{dist_sym, emit_fixed_block, length_sym};
use deflate_core::tokens::Token;

#[derive(Clone, Copy)]
pub struct Settings {
    pub limit: usize,
    pub minimum: usize,
    pub stored: bool,
}
impl Settings {
    pub fn parse(text: &str) -> Result<Self, String> {
        let fields: Vec<_> = text.split(':').collect();
        if fields.len() != 5 || fields[0] != "stream" || fields[1] != "16384" || fields[4] != "best"
        {
            return Err("expected stream:16384:MINIMUM(0/256):STORED(0/1):best".into());
        }
        let minimum = match fields[2] {
            "0" => 0,
            "256" => 256,
            _ => return Err("unsupported streaming minimum".into()),
        };
        let stored = match fields[3] {
            "0" => false,
            "1" => true,
            _ => return Err("stored must be 0 or 1".into()),
        };
        Ok(Self {
            limit: 16384,
            minimum,
            stored,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Kind {
    Fixed,
    Dynamic,
    Stored,
}

#[derive(Default)]
pub struct Stats {
    pub blocks: usize,
    pub stored_blocks: usize,
    pub dynamic_blocks: usize,
    pub adaptive_boundaries: usize,
    pub maximum_buffer_tokens: usize,
    pub cross_block_matches: usize,
    pub matches_after_stored: usize,
    pub huffman_analyses: usize,
    pub attempted_stream_bits: usize,
    pub whole_stored_fallback: bool,
}
pub struct Output {
    pub packet: Vec<u8>,
    pub stats: Stats,
}

fn width(token: Token) -> usize {
    match token {
        Token::Literal(_) => 1,
        Token::Match { len, .. } => usize::from(len),
    }
}
fn long(token: Token) -> bool {
    matches!(token, Token::Match { len: 8.., .. })
}
fn classify(count: usize) -> Option<bool> {
    if count <= 8 {
        Some(false)
    } else if count >= 32 {
        Some(true)
    } else {
        None
    }
}
fn add(freqs: &mut Freqs, token: Token) {
    match token {
        Token::Literal(b) => freqs.lit[usize::from(b)] += 1,
        Token::Match { len, dist } => {
            freqs.lit[usize::from(length_sym(len).0)] += 1;
            freqs.dist[usize::from(dist_sym(dist).0)] += 1;
        }
    }
}
pub fn stored_bits(raw: usize, offset: usize) -> usize {
    let chunks = raw.div_ceil(65535).max(1);
    3 + (8 - (offset + 3) % 8) % 8 + 32 + raw * 8 + (chunks - 1) * 40
}
fn emit_stored(writer: &mut BitWriter, final_: bool, raw: &[u8]) {
    let count = raw.len().div_ceil(65535).max(1);
    for index in 0..count {
        let part = &raw[index * 65535..raw.len().min((index + 1) * 65535)];
        writer.write_bits(u32::from(final_ && index + 1 == count), 1);
        writer.write_bits(0, 2);
        writer.write_bits(0, ((8 - writer.bit_len() % 8) % 8) as u32);
        let len = part.len() as u16;
        writer.write_bits(u32::from(len), 16);
        writer.write_bits(u32::from(!len), 16);
        for &byte in part {
            writer.write_bits(u32::from(byte), 8);
        }
    }
}

fn encode_tokens<const RECORD: bool>(
    raw: &[u8],
    settings: Settings,
    tokens: impl Iterator<Item = Token>,
) -> Output {
    let mut tokens = tokens.fuse().peekable();
    let mut chunk = Vec::with_capacity(settings.limit);
    let mut freqs = Freqs::from_tokens(&[]);
    let (mut buffered_raw, mut raw_start) = (0, 0);
    let mut writer = BitWriter::new();
    let mut stats = Stats::default();
    let mut preceding_stored = false;
    let mut stable = None;
    let mut pending = None;
    let mut window_long = 0;
    loop {
        let mut split = None;
        while chunk.len() < settings.limit {
            let Some(token) = tokens.next() else { break };
            add(&mut freqs, token);
            buffered_raw += width(token);
            window_long += usize::from(long(token));
            chunk.push(token);
            if settings.minimum != 0 && chunk.len() % 64 == 0 {
                let regime = classify(window_long);
                window_long = 0;
                if let Some(current) = regime {
                    if stable.is_none() {
                        stable = Some(current);
                    }
                    if stable != Some(current) {
                        if pending == Some(current) && chunk.len() >= settings.minimum + 128 {
                            split = Some(chunk.len() - 128);
                            break;
                        }
                        pending = Some(current);
                    } else {
                        pending = None;
                    }
                } else {
                    pending = None;
                }
            } else if chunk.len() % 64 == 0 {
                window_long = 0;
            }
        }
        let count = split.unwrap_or(chunk.len());
        let last = count == chunk.len() && tokens.peek().is_none();
        let tail = Freqs::from_tokens(&chunk[count..]); // At most 128 retained tokens.
        let tail_raw: usize = chunk[count..].iter().copied().map(width).sum();
        let mut selected = freqs.clone();
        for (f, &t) in selected.lit.iter_mut().zip(&tail.lit) {
            *f -= t;
        }
        selected.lit[256] = 1;
        for (f, &t) in selected.dist.iter_mut().zip(&tail.dist) {
            *f -= t;
        }
        let raw_end = raw_start + buffered_raw - tail_raw;
        let fixed = selected.fixed_bits();
        let lengths = lengths_for_freqs(&selected);
        let dynamic = lengths
            .as_ref()
            .map(|(l, d, c)| selected.dynamic_bits(l, d, c));
        let mut kind = Kind::Fixed;
        let mut bits = fixed;
        if let Some(n) = dynamic
            && n < bits
        {
            kind = Kind::Dynamic;
            bits = n;
        }
        let stored = stored_bits(raw_end - raw_start, writer.bit_len() % 8);
        if settings.stored && stored < bits {
            kind = Kind::Stored;
            bits = stored;
        }
        if RECORD {
            assert_eq!(selected, Freqs::from_tokens(&chunk[..count]));
            stats.blocks += 1;
            stats.stored_blocks += usize::from(kind == Kind::Stored);
            stats.dynamic_blocks += usize::from(kind == Kind::Dynamic);
            stats.adaptive_boundaries += usize::from(split.is_some());
            stats.maximum_buffer_tokens = stats.maximum_buffer_tokens.max(chunk.len());
            stats.huffman_analyses += 1;
            let mut position = raw_start;
            for &t in &chunk[..count] {
                if let Token::Match { dist, .. } = t {
                    stats.cross_block_matches +=
                        usize::from(usize::from(dist) > position - raw_start);
                    stats.matches_after_stored +=
                        usize::from(preceding_stored && usize::from(dist) > position - raw_start);
                }
                position += width(t);
            }
        }
        let before = writer.bit_len();
        match kind {
            Kind::Fixed => emit_fixed_block(&mut writer, last, chunk[..count].iter().copied()),
            Kind::Dynamic => {
                let (l, d, c) = lengths.as_ref().unwrap();
                emit_dynamic_block(&mut writer, last, l, d, c, &chunk[..count]);
            }
            Kind::Stored => emit_stored(&mut writer, last, &raw[raw_start..raw_end]),
        }
        if RECORD {
            assert_eq!(writer.bit_len() - before, bits);
        }
        preceding_stored = kind == Kind::Stored;
        raw_start = raw_end;
        if last {
            break;
        }
        chunk.drain(..count);
        freqs = tail;
        buffered_raw = tail_raw;
        stable = if chunk.len() >= 64 {
            classify(
                chunk[chunk.len() - 64..]
                    .iter()
                    .filter(|&&t| long(t))
                    .count(),
            )
        } else {
            None
        };
        pending = None;
        window_long = chunk[chunk.len() / 64 * 64..]
            .iter()
            .filter(|&&t| long(t))
            .count();
    }
    assert_eq!(raw_start, raw.len());
    if RECORD {
        stats.attempted_stream_bits = writer.bit_len();
    }
    let packet = writer.finish();
    let whole_stored = raw.len() + raw.len().div_ceil(65535).max(1) * 5;
    if packet.len() < whole_stored {
        Output { packet, stats }
    } else {
        if RECORD {
            stats.whole_stored_fallback = true;
        }
        Output {
            packet: deflate_core::deflate_stored(raw),
            stats,
        }
    }
}
pub fn encode<const RECORD: bool>(raw: &[u8], settings: Settings) -> Output {
    encode_tokens::<RECORD>(
        raw,
        settings,
        deflate_core::matcher::tokens_with_level(raw, CompressionLevel::Best),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn check(packet: &[u8], raw: &[u8]) {
        assert_eq!(deflate_core::inflate(packet).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(packet).unwrap(),
            raw
        );
    }
    fn random(n: usize) -> Vec<u8> {
        let mut s = 1951_u32;
        (0..n)
            .map(|_| {
                s ^= s << 13;
                s ^= s >> 17;
                s ^= s << 5;
                s as u8
            })
            .collect()
    }
    #[test]
    fn stored_append_all_offsets_and_length_boundaries() {
        for prefix in 0..8 {
            for n in [0, 1, 65535, 65536, 131071] {
                let raw = random(n);
                let mut w = BitWriter::new();
                emit_fixed_block(&mut w, false, (0..prefix).map(|_| Token::Literal(144)));
                let before = w.bit_len();
                assert_eq!(before % 8, (2 + prefix) % 8);
                emit_stored(&mut w, true, &raw);
                assert_eq!(w.bit_len() - before, stored_bits(n, before % 8));
                let mut expected = vec![144; prefix];
                expected.extend(raw);
                check(&w.finish(), &expected);
            }
        }
    }
    #[test]
    fn identical_partitions_and_instrumentation_preserve_packets() {
        for n in [0, 1, 259, 16384, 32769, 65537, 131073] {
            let mut raw = random(n);
            for i in 0..n {
                if i % 8192 >= 4096 {
                    raw[i] = b"abcabcdef"[i % 9];
                }
            }
            let tokens: Vec<_> =
                deflate_core::matcher::tokens_with_level(&raw, CompressionLevel::Best).collect();
            let expected = deflate_core::encode_dynamic::emit_blocks(
                &tokens,
                deflate_core::compress::default_split_for,
            );
            let stored = deflate_core::deflate_stored(&raw);
            let expected = if expected.len() < stored.len() {
                expected
            } else {
                stored
            };
            let settings = Settings::parse("stream:16384:0:0:best").unwrap();
            assert_eq!(encode::<false>(&raw, settings).packet, expected);
            for text in ["stream:16384:0:1:best", "stream:16384:256:1:best"] {
                let settings = Settings::parse(text).unwrap();
                let output = encode::<true>(&raw, settings);
                assert_eq!(output.packet, encode::<false>(&raw, settings).packet);
                assert!(output.stats.maximum_buffer_tokens <= 16384);
                check(&output.packet, &raw);
            }
        }
    }
    #[test]
    fn stored_to_compressed_blocks_keep_dictionary_history() {
        let mut raw = random(16384);
        raw.extend_from_within(..);
        let mut tokens: Vec<_> = raw[..16384].iter().copied().map(Token::Literal).collect();
        let mut remaining = 16384;
        while remaining > 0 {
            let len = remaining.min(258);
            tokens.push(Token::Match {
                len: len as u16,
                dist: 16384,
            });
            remaining -= len;
        }
        // The final remainder is >=3 for this input.
        assert_eq!(deflate_core::tokens::expand(&tokens).unwrap(), raw);
        let settings = Settings::parse("stream:16384:0:1:best").unwrap();
        let output = encode_tokens::<true>(&raw, settings, tokens.into_iter());
        assert!(output.stats.stored_blocks > 0 && output.stats.matches_after_stored > 0);
        assert!(!output.stats.whole_stored_fallback);
        check(&output.packet, &raw);
        let mut changed = random(2048);
        changed.extend((0..65536).map(|i| b"abcabcxyz"[i % 9]));
        let output = encode::<true>(
            &changed,
            Settings::parse("stream:16384:256:1:best").unwrap(),
        );
        assert!(output.stats.adaptive_boundaries > 0);
        check(&output.packet, &changed);
    }
}
