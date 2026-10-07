//! Isolated research parser: exact short oracle or a bounded candidate graph.
use deflate_core::encode_fixed::{dist_sym, length_sym};
use deflate_core::tokens::Token;

const fn compile_number(text: Option<&str>, fallback: usize) -> usize {
    let Some(value) = text else {
        return fallback;
    };
    let bytes = value.as_bytes();
    let mut out = 0;
    let mut index = 0;
    while index < bytes.len() {
        assert!(bytes[index] >= b'0' && bytes[index] <= b'9');
        out = out * 10 + (bytes[index] - b'0') as usize;
        index += 1;
    }
    out
}

pub const HASH_BITS: usize = compile_number(option_env!("DEFLATED_RESEARCH_HASH_BITS"), 15);
pub const WINDOW: usize = compile_number(option_env!("DEFLATED_RESEARCH_WINDOW"), 32768);
const _: () = assert!(HASH_BITS >= 12 && HASH_BITS <= 18);
const _: () = assert!(WINDOW >= 1024 && WINDOW <= 32768 && WINDOW.is_power_of_two());

#[derive(Clone, Copy)]
pub struct Settings {
    pub exact: bool,
    pub cost: bool,
    pub probes: usize,
    pub block_bytes: usize,
}

fn literal_bits(byte: u8) -> u64 {
    if byte <= 143 { 8 } else { 9 }
}

pub fn match_bits(len: u16, dist: u16) -> u64 {
    let (symbol, _, length_extra) = length_sym(len);
    let (_, _, distance_extra) = dist_sym(dist);
    let length_code = if symbol <= 279 { 7_u32 } else { 8 };
    u64::from(length_code + length_extra + 5 + distance_extra)
}

fn match_length(raw: &[u8], pos: usize, previous: usize, end: usize) -> usize {
    let mut len = 0;
    let bound = (end - pos).min(258);
    while len < bound && raw[pos + len] == raw[previous + len] {
        len += 1;
    }
    len
}

pub fn parse(raw: &[u8], settings: Settings) -> Vec<Token> {
    assert!(!settings.exact || raw.len() <= 4096);
    assert!(settings.block_bytes > 0 && settings.probes > 0);
    let mut head = vec![usize::MAX; 1 << HASH_BITS];
    let mut previous = vec![usize::MAX; WINDOW];
    let mut result = Vec::new();
    for start in (0..raw.len()).step_by(settings.block_bytes) {
        let end = raw.len().min(start.saturating_add(settings.block_bytes));
        let mut candidates = Vec::with_capacity(end - start);
        for pos in start..end {
            let mut matches = Vec::new();
            if settings.exact {
                for distance in 1..=pos.min(32768) {
                    let length = match_length(raw, pos, pos - distance, end);
                    if length >= 3 {
                        matches.push((length as u16, distance as u16));
                    }
                }
            } else if raw.len() - pos >= 3 {
                let key = (u32::from(raw[pos])
                    | (u32::from(raw[pos + 1]) << 8)
                    | (u32::from(raw[pos + 2]) << 16))
                    .wrapping_mul(0x1e35_a7bd);
                let slot = (key >> (32 - HASH_BITS)) as usize;
                let mut found = head[slot];
                let mut longest_seen = 2;
                for _ in 0..settings.probes {
                    if found == usize::MAX || found >= pos || pos - found > WINDOW {
                        break;
                    }
                    let length = match_length(raw, pos, found, end);
                    // Links visit increasing distances. A nearer match with
                    // at least this length dominates fixed-bit prefix costs.
                    if length > longest_seen {
                        matches.push((length as u16, (pos - found) as u16));
                        longest_seen = length;
                        if length == (end - pos).min(258) {
                            break;
                        }
                    }
                    let next = previous[found & (WINDOW - 1)];
                    if next >= found {
                        break;
                    }
                    found = next;
                }
                previous[pos & (WINDOW - 1)] = head[slot];
                head[slot] = pos;
            }
            candidates.push(matches);
        }
        let mut costs = if settings.cost {
            vec![0_u64; end - start + 1]
        } else {
            Vec::new()
        };
        let mut choices = if settings.cost {
            vec![Token::Literal(0); end - start]
        } else {
            Vec::new()
        };
        if settings.cost {
            for pos in (start..end).rev() {
                let offset = pos - start;
                costs[offset] = literal_bits(raw[pos]) + costs[offset + 1];
                choices[offset] = Token::Literal(raw[pos]);
                // For each legal prefix length, retain the cheapest distance.
                // Fixed distance costs are monotone, so nearest wins ties too.
                let mut distances = [0_u16; 259];
                let mut maximum = 0;
                for &(length, distance) in &candidates[offset] {
                    maximum = maximum.max(usize::from(length));
                    for selected in distances.iter_mut().take(usize::from(length) + 1).skip(3) {
                        if *selected == 0 || distance < *selected {
                            *selected = distance;
                        }
                    }
                }
                for (count, &distance) in distances.iter().enumerate().take(maximum + 1).skip(3) {
                    if distance == 0 {
                        continue;
                    }
                    let cost = match_bits(count as u16, distance) + costs[offset + count];
                    if cost < costs[offset] {
                        costs[offset] = cost;
                        choices[offset] = Token::Match {
                            len: count as u16,
                            dist: distance,
                        };
                    }
                }
            }
        }
        let mut pos = start;
        while pos < end {
            let token = if settings.cost {
                choices[pos - start]
            } else {
                candidates[pos - start]
                    .iter()
                    .min_by_key(|&&(length, distance)| {
                        (
                            std::cmp::Reverse(length),
                            match_bits(length, distance),
                            distance,
                        )
                    })
                    .map_or(Token::Literal(raw[pos]), |&(len, dist)| Token::Match {
                        len,
                        dist,
                    })
            };
            pos += match token {
                Token::Literal(_) => 1,
                Token::Match { len, .. } => usize::from(len),
            };
            result.push(token);
        }
    }
    result
}
