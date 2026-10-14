//! Full block equivalence, including error precedence, bit position and partial
//! output. The reference uses canonical bit-at-a-time Huffman decoding and a
//! byte-at-a-time LZ77 copy, independently of the optimized token/copy paths.
use deflate_core::block::decode_huff_block;
use deflate_core::huffman::{Completeness, HuffmanTable, fixed_dist, fixed_litlen};
use deflate_core::lz77::{DIST_BASE, LENGTH_BASE, read_distance, read_length};
use deflate_core::tokens::Token;
use deflate_core::{Error, bitstream::BitReader, bitwriter::BitWriter};

fn scalar(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    r: &mut BitReader<'_>,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    loop {
        let sym = lit.decode(r)?;
        if sym < 256 {
            if out.len() >= limit {
                return Err(Error::OutputLimitExceeded);
            }
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let len = read_length(sym, r)?;
            let distance = read_distance(dist.decode(r)?, r)?;
            if out.len().saturating_add(len) > limit {
                return Err(Error::OutputLimitExceeded);
            }
            if distance == 0 || distance > out.len() {
                return Err(Error::InvalidDistance);
            }
            for _ in 0..len {
                out.push(out[out.len() - distance]);
            }
        }
    }
}

fn check(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    bytes: &[u8],
    start: usize,
    history: &[u8],
    limit: usize,
) {
    let mut actual = BitReader::new(bytes);
    let mut reference = BitReader::new(bytes);
    actual.skip_bits(start);
    reference.skip_bits(start);
    let mut out = history.to_vec();
    let mut expected = history.to_vec();
    let got = decode_huff_block(lit, dist, &mut actual, &mut out, limit);
    let want = scalar(lit, dist, &mut reference, &mut expected, limit);
    assert_eq!(
        (got, actual.bit_pos(), out),
        (want, reference.bit_pos(), expected),
        "start={start}, bytes={}, history={}, limit={limit}",
        bytes.len(),
        history.len()
    );
}

fn next(seed: &mut u64) -> u64 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    *seed
}

fn lengths(seed: &mut u64, alphabet: usize) -> Vec<u8> {
    let mut leaves = vec![0];
    let count = 2 + next(seed) as usize % (alphabet - 1);
    while leaves.len() < count {
        let i = next(seed) as usize % leaves.len();
        if leaves[i] == 15 {
            continue;
        }
        leaves[i] += 1;
        leaves.push(leaves[i]);
    }
    let mut result = vec![0; alphabet];
    let mut slots: Vec<_> = (0..alphabet).collect();
    for len in leaves {
        let i = next(seed) as usize % slots.len();
        result[slots.swap_remove(i)] = len;
    }
    result
}

#[test]
fn malformed_and_truncated_blocks_match_scalar_state() {
    let mut seed = 0x1951_d3f1_a7e5_9876;
    let history: Vec<u8> = (0..128).collect();
    let mut tables = vec![(fixed_litlen(), fixed_dist())];
    for _ in 0..20 {
        let lit =
            HuffmanTable::from_lengths(&lengths(&mut seed, 288), Completeness::Complete).unwrap();
        let dist =
            HuffmanTable::from_lengths(&lengths(&mut seed, 32), Completeness::Complete).unwrap();
        tables.push((lit, dist));
    }
    for len in [0, 1, 12, 13, 15] {
        let mut lens = [0; 30];
        lens[29] = len;
        tables.push((
            fixed_litlen(),
            HuffmanTable::from_lengths(&lens, Completeness::AllowDegenerate).unwrap(),
        ));
    }
    for (lit, dist) in tables {
        for _ in 0..16 {
            let bytes: Vec<u8> = (0..80).map(|_| next(&mut seed) as u8).collect();
            for end in 0..=bytes.len() {
                let start = end % 8;
                check(&lit, &dist, &bytes[..end], start, &history, 1024);
                check(&lit, &dist, &bytes[..end], start, &[], 0);
            }
        }
    }
}

#[test]
fn all_length_distance_ranges_and_limit_boundaries_match() {
    let lit = fixed_litlen();
    let dist = fixed_dist();
    let history: Vec<u8> = (0..32768).map(|i| (i * 31) as u8).collect();
    let mut tokens = Vec::new();
    for length in LENGTH_BASE {
        for distance in DIST_BASE {
            tokens.push(Token::Match {
                len: length,
                dist: distance,
            });
        }
    }
    tokens.extend([
        Token::Match {
            len: 258,
            dist: 32768,
        },
        Token::Literal(0xff),
    ]);
    for offset in 0..8 {
        let mut writer = BitWriter::new();
        writer.write_bits(0, offset);
        deflate_core::encode_fixed::emit_fixed_block(&mut writer, true, tokens.clone());
        let mut bytes = writer.finish();
        // Lookahead may include a container suffix, but must never consume it.
        bytes.extend_from_slice(&[0xa5; 16]);
        for limit in [0, 32767, 32768, 32769, 32771, 33026, 200000] {
            check(&lit, &dist, &bytes, offset as usize + 3, &history, limit);
        }
        for end in (0..bytes.len())
            .step_by(31)
            .chain(bytes.len().saturating_sub(10)..bytes.len())
        {
            check(
                &lit,
                &dist,
                &bytes[..end],
                offset as usize + 3,
                &history,
                200000,
            );
        }
    }
}

#[test]
fn reserved_codes_and_error_precedence_match() {
    for sym in [257u16, 285, 286, 287] {
        for distance in [0, 29, 30, 31] {
            let mut writer = BitWriter::new();
            if sym < 280 {
                writer.write_code(u32::from(sym - 256), 7);
            } else {
                writer.write_code(u32::from(0xc0 + sym - 280), 8);
            }
            writer.write_code(distance, 5);
            writer.write_bits(8191, 13);
            let mut bytes = writer.finish();
            bytes.extend_from_slice(&[0; 16]);
            for limit in [0, 2, 258, 1000] {
                check(&fixed_litlen(), &fixed_dist(), &bytes, 0, b"x", limit);
            }
        }
    }
}

#[test]
fn buffered_literals_and_long_code_fallback_preserve_state() {
    // A complete comb tree: 0 has a one-bit code; 65 and EOB have
    // fifteen-bit codes, forcing canonical fallback between buffered runs.
    let mut lengths = [0; 257];
    for (symbol, length) in lengths.iter_mut().enumerate().take(14) {
        *length = symbol as u8 + 1;
    }
    lengths[65] = 15;
    lengths[256] = 15;
    let lit = HuffmanTable::from_lengths(&lengths, Completeness::Complete).unwrap();
    let dist = fixed_dist();
    for offset in 0..8 {
        let mut writer = BitWriter::new();
        writer.write_bits(0, offset);
        for run in [1, 15, 16, 17, 41, 42, 56, 57, 64] {
            for _ in 0..run {
                writer.write_code(0, 1);
            }
            writer.write_code(0x7ffe, 15);
        }
        writer.write_code(0x7fff, 15);
        let mut bytes = writer.finish();
        bytes.extend_from_slice(&[0xa5; 16]);
        for limit in 0..=400 {
            check(&lit, &dist, &bytes, offset as usize, &[], limit);
        }
        for end in 0..=bytes.len() {
            check(&lit, &dist, &bytes[..end], offset as usize, &[], 400);
        }
    }
}
