use crate::decode::expand;
use crate::wire::{Error, check, put_varint, varint_len};
use alloc::collections::BTreeMap;
use alloc::vec::Vec;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DictionaryMode {
    Off,
    Keys,
    AllQuoted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Settings {
    pub chunk_log2: u8,
    pub dictionary: DictionaryMode,
    pub numbers: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            chunk_log2: 16,
            dictionary: DictionaryMode::Keys,
            numbers: true,
        }
    }
}

#[derive(Clone, Copy)]
enum Kind {
    Literal,
    Quoted(bool),
    Number(u64),
}

struct Span {
    start: usize,
    end: usize,
    kind: Kind,
}

fn canonical_integer(bytes: &[u8]) -> Option<u64> {
    if bytes.is_empty() || bytes.len() > 20 || (bytes.len() > 1 && bytes[0] == b'0') {
        return None;
    }
    bytes.iter().try_fold(0_u64, |value, &byte| {
        if byte.is_ascii_digit() {
            value.checked_mul(10)?.checked_add(u64::from(byte - b'0'))
        } else {
            None
        }
    })
}

fn scan(raw: &[u8], numbers: bool) -> Vec<Span> {
    let mut spans = Vec::new();
    let mut cursor = 0;
    while cursor < raw.len() {
        let start = cursor;
        let mut kind = Kind::Literal;
        if raw[cursor] == b'"' {
            cursor += 1;
            let mut closed = false;
            while cursor < raw.len() {
                match raw[cursor] {
                    b'\\' => cursor = (cursor + 2).min(raw.len()),
                    b'"' => {
                        cursor += 1;
                        closed = true;
                        break;
                    }
                    _ => cursor += 1,
                }
            }
            if closed {
                let mut next = cursor;
                while next < raw.len() && b" \t\r\n".contains(&raw[next]) {
                    next += 1;
                }
                kind = Kind::Quoted(raw.get(next) == Some(&b':'));
            }
        } else if numbers && (raw[cursor].is_ascii_digit() || b"+-.".contains(&raw[cursor])) {
            cursor += 1;
            while cursor < raw.len() && b"0123456789+-eE.".contains(&raw[cursor]) {
                cursor += 1;
            }
            let adjacent = |byte: &u8| byte.is_ascii_alphabetic() || *byte == b'_';
            if !raw.get(start.wrapping_sub(1)).is_some_and(adjacent)
                && !raw.get(cursor).is_some_and(adjacent)
                && let Some(value) = canonical_integer(&raw[start..cursor])
            {
                kind = Kind::Number(value);
            }
        } else {
            cursor += 1;
        }
        spans.push(Span {
            start,
            end: cursor,
            kind,
        });
    }
    spans
}

fn propose(raw: &[u8], settings: Settings) -> [Vec<u8>; 4] {
    let spans = scan(raw, settings.numbers);
    let mut counts = BTreeMap::<&[u8], (usize, usize)>::new();
    if settings.dictionary != DictionaryMode::Off {
        for span in &spans {
            if let Kind::Quoted(key) = span.kind
                && (key || settings.dictionary == DictionaryMode::AllQuoted)
                && span.end - span.start <= 256
            {
                let record = counts
                    .entry(&raw[span.start..span.end])
                    .or_insert((0, span.start));
                record.0 += 1;
            }
        }
    }
    let mut ranked = counts
        .into_iter()
        .filter_map(|(entry, (count, first))| {
            let score = (count as i64) * (entry.len() as i64 - 3)
                - entry.len() as i64
                - varint_len(entry.len() as u64) as i64;
            (count >= 3 && score > 0).then_some((entry, score, first))
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then(a.2.cmp(&b.2)).then(a.0.cmp(b.0)));
    let mut dictionary_body = Vec::new();
    let mut ids = BTreeMap::new();
    for (entry, _, _) in ranked {
        if ids.len() == 256 {
            break;
        }
        let body_size = dictionary_body.len() + varint_len(entry.len() as u64) + entry.len();
        if body_size + varint_len(ids.len() as u64 + 1) > 65536 {
            continue;
        }
        ids.insert(entry, ids.len() as u64);
        put_varint(entry.len() as u64, &mut dictionary_body);
        dictionary_body.extend_from_slice(entry);
    }
    let mut streams = [Vec::new(), Vec::new(), Vec::new(), Vec::new()];
    put_varint(ids.len() as u64, &mut streams[0]);
    streams[0].extend_from_slice(&dictionary_body);
    let mut literal_start = 0;
    let mut previous = None;
    for span in &spans {
        let id = match span.kind {
            Kind::Quoted(key) if key || settings.dictionary == DictionaryMode::AllQuoted => {
                ids.get(&raw[span.start..span.end]).copied()
            }
            _ => None,
        };
        let numeric = if let Kind::Number(value) = span.kind {
            Some(value)
        } else {
            None
        };
        if id.is_none() && numeric.is_none() {
            continue;
        }
        if literal_start < span.start {
            streams[1].push(0);
            put_varint((span.start - literal_start) as u64, &mut streams[1]);
            streams[2].extend_from_slice(&raw[literal_start..span.start]);
        }
        if let Some(id) = id {
            streams[1].push(1);
            put_varint(id, &mut streams[1]);
        } else if let Some(value) = numeric {
            let delta = previous.and_then(|previous| {
                let delta = i128::from(value) - i128::from(previous);
                if !(i128::from(i64::MIN)..=i128::from(i64::MAX)).contains(&delta) {
                    return None;
                }
                let zigzag = if delta >= 0 {
                    2 * delta
                } else {
                    -2 * delta - 1
                } as u64;
                (varint_len(zigzag) < varint_len(value)).then_some(zigzag)
            });
            streams[1].push(if delta.is_some() { 3 } else { 2 });
            put_varint(delta.unwrap_or(value), &mut streams[3]);
            previous = Some(value);
        }
        literal_start = span.end;
    }
    if literal_start < raw.len() {
        streams[1].push(0);
        put_varint((raw.len() - literal_start) as u64, &mut streams[1]);
        streams[2].extend_from_slice(&raw[literal_start..]);
    }
    streams
}

fn transform(raw: &[u8], settings: Settings) -> Option<Vec<u8>> {
    let streams = propose(raw, settings);
    // The proposal is not trusted. Reconstruction work is part of encode.
    if expand(&streams, raw.len()).ok()?.as_slice() != raw {
        return None;
    }
    let mut descriptors = Vec::new();
    let mut payloads = Vec::new();
    for stream in streams {
        let compressed = deflate_core::deflate(&stream);
        let use_compressed = compressed.len() < stream.len();
        let payload = if use_compressed { &compressed } else { &stream };
        descriptors.extend_from_slice(&(stream.len() as u32).to_le_bytes());
        descriptors.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        descriptors.extend_from_slice(&[u8::from(use_compressed), 0, 0, 0]);
        payloads.extend_from_slice(payload);
    }
    descriptors.extend_from_slice(&payloads);
    Some(descriptors)
}

fn encode_impl(raw: &[u8], settings: Settings, transformed: bool) -> Result<Vec<u8>, Error> {
    check(
        settings.chunk_log2 == 16 || settings.chunk_log2 == 18,
        Error::InvalidLength,
    )?;
    let chunk_size = 1_usize << settings.chunk_log2;
    let count = raw.len().div_ceil(chunk_size);
    check(count <= u32::MAX as usize, Error::InvalidLength)?;
    let mut out = Vec::new();
    out.extend_from_slice(b"DSC1");
    out.extend_from_slice(&[1, settings.chunk_log2, 0, 0]);
    out.extend_from_slice(&(raw.len() as u64).to_le_bytes());
    out.extend_from_slice(&(count as u32).to_le_bytes());
    out.extend_from_slice(&deflate_core::crc32::Crc32::compute(raw).to_le_bytes());
    for chunk in raw.chunks(chunk_size) {
        let split = if transformed {
            transform(chunk, settings)
        } else {
            None
        };
        let ordinary = deflate_core::deflate(chunk);
        let (mut mode, mut payload) = if ordinary.len() < chunk.len() {
            (1, ordinary.as_slice())
        } else {
            (0, chunk)
        };
        if let Some(split) = &split
            && split.len() < payload.len()
        {
            mode = 2;
            payload = split;
        }
        out.extend_from_slice(&[mode, 0, 0, 0]);
        out.extend_from_slice(&(chunk.len() as u32).to_le_bytes());
        out.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        out.extend_from_slice(&deflate_core::crc32::Crc32::compute(chunk).to_le_bytes());
        out.extend_from_slice(payload);
    }
    Ok(out)
}

pub fn encode(raw: &[u8], settings: Settings) -> Result<Vec<u8>, Error> {
    encode_impl(raw, settings, true)
}

pub fn encode_untransformed(raw: &[u8], settings: Settings) -> Result<Vec<u8>, Error> {
    encode_impl(raw, settings, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numeric_spellings_and_extrema_remain_exact() {
        let raw = b"[-0,+0,0007,1.0,1e3,18446744073709551616,18446744073709551615,0,9223372036854775807,9223372036854775808,foo7,7bar,_7,7_]";
        let streams = propose(raw, Settings::default());
        assert_eq!(expand(&streams, raw.len()).unwrap(), raw);
        let spans = scan(raw, true);
        let values = spans
            .iter()
            .filter_map(|s| match s.kind {
                Kind::Number(n) => Some(n),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(values, [u64::MAX, 0, i64::MAX as u64, 1 << 63]);
    }

    #[test]
    fn quoted_escapes_duplicates_and_invalid_bytes_are_not_parsed() {
        let raw = b"{\"abc\\\"def\":1,\"abc\\\"def\":2,\"abc\\\"def\":3,\"x\":\"\xff\\u0061\"} unfinished \"123\\";
        for dictionary in [
            DictionaryMode::Off,
            DictionaryMode::Keys,
            DictionaryMode::AllQuoted,
        ] {
            let streams = propose(
                raw,
                Settings {
                    dictionary,
                    ..Settings::default()
                },
            );
            assert_eq!(expand(&streams, raw.len()).unwrap(), raw);
        }
    }

    #[test]
    fn keys_mode_keeps_identical_value_lexemes_literal() {
        let raw = b"{\"repeatkey\":1,\"repeatkey\":2,\"repeatkey\":3,\"x\":\"repeatkey\"}";
        let streams = propose(
            raw,
            Settings {
                numbers: false,
                ..Settings::default()
            },
        );
        assert!(streams[2].ends_with(b",\"x\":\"repeatkey\"}"));
        assert_eq!(expand(&streams, raw.len()).unwrap(), raw);
    }
}
