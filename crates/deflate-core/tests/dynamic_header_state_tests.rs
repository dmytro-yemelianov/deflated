//! Compare the bounded stack parser with the original growable parser,
//! using canonical symbol decoding in the reference. Errors and cursor are
//! part of the contract, including malformed headers and repeat overruns.
use deflate_core::Error;
use deflate_core::bitstream::BitReader;
use deflate_core::bitwriter::BitWriter;
use deflate_core::block::{CL_ORDER, read_dynamic_tables};
use deflate_core::huffman::{Completeness, HuffmanTable};

fn reference_dynamic_tables(r: &mut BitReader) -> Result<(HuffmanTable, HuffmanTable), Error> {
    let nlen = r.read_bits(5)? as usize + 257;
    let ndist = r.read_bits(5)? as usize + 1;
    let ncode = r.read_bits(4)? as usize + 4;
    // The 5-bit fields can express more than RFC 1951 permits.
    if nlen > 286 || ndist > 30 {
        return Err(Error::InvalidHuffmanTree);
    }

    let mut cl_lengths = [0u8; 19];
    for &slot in CL_ORDER.iter().take(ncode) {
        let v = r.read_bits(3)? as u8;
        match cl_lengths.get_mut(slot) {
            Some(c) => *c = v,
            None => return Err(Error::InvalidHuffmanTree),
        }
    }
    let cl = HuffmanTable::from_lengths(&cl_lengths, Completeness::Complete)?;

    let total = nlen + ndist;
    let mut lengths = vec![0u8; 0];
    lengths.reserve(total);
    while lengths.len() < total {
        // The table is built anyway; `decodeSymFast_eq` holds for every code.
        let sym = cl.decode(r)?;
        match sym {
            0..=15 => lengths.push(sym as u8),
            16 => {
                let prev = match lengths.last() {
                    Some(p) => *p,
                    None => return Err(Error::InvalidHuffmanTree),
                };
                let n = 3 + r.read_bits(2)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, prev);
            }
            17 => {
                let n = 3 + r.read_bits(3)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            18 => {
                let n = 11 + r.read_bits(7)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            _ => return Err(Error::InvalidHuffmanTree),
        }
    }

    let (lit_lens, dist_lens) = match lengths.split_at_checked(nlen) {
        Some(p) => p,
        None => return Err(Error::InvalidHuffmanTree),
    };
    let lit = HuffmanTable::from_lengths(lit_lens, Completeness::Complete)?;
    // ADR 0004: only the distance tree is allowed to be degenerate.
    let dist = HuffmanTable::from_lengths(dist_lens, Completeness::AllowDegenerate)?;
    Ok((lit, dist))
}

fn check(bytes: &[u8], start: usize) {
    let mut actual = BitReader::new(bytes);
    let mut reference = BitReader::new(bytes);
    actual.skip_bits(start);
    reference.skip_bits(start);
    assert_eq!(
        read_dynamic_tables(&mut actual),
        reference_dynamic_tables(&mut reference)
    );
    assert_eq!(actual.bit_pos(), reference.bit_pos());
}

#[test]
fn valid_header_at_all_offsets_and_truncations() {
    let packet = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
    for offset in 0..8 {
        let mut writer = BitWriter::new();
        writer.write_bits(0, offset);
        for &byte in packet {
            writer.write_bits(u32::from(byte), 8);
        }
        let bytes = writer.finish();
        for end in 0..=bytes.len().min(128) {
            check(&bytes[..end], offset as usize + 3);
        }
    }
}

#[test]
fn repeat_codes_at_the_maximum_header_boundary_and_random_headers() {
    // Four equally long code-length codes: 0, 16, 17, 18. Every repeat
    // branch is reached, including missing previous length and overruns.
    for nlen in [0, 29] {
        for ndist in [0, 29] {
            for symbol in 0..4 {
                for prefix in [false, true] {
                    for offset in 0..8 {
                        let mut writer = BitWriter::new();
                        writer.write_bits(0, offset);
                        writer.write_bits(nlen, 5);
                        writer.write_bits(ndist, 5);
                        writer.write_bits(0, 4);
                        for _ in 0..4 {
                            writer.write_bits(2, 3);
                        }
                        if prefix {
                            writer.write_code(0, 2);
                        }
                        for _ in 0..110 {
                            writer.write_code(symbol, 2);
                            let extra = [0, 2, 3, 7][symbol as usize];
                            writer.write_bits((1 << extra) - 1, extra);
                        }
                        let bytes = writer.finish();
                        for end in 0..=bytes.len() {
                            check(&bytes[..end], offset as usize);
                        }
                    }
                }
            }
        }
    }
    let mut seed = 0x1951u64;
    for _ in 0..2000 {
        let mut bytes = [0; 128];
        for byte in &mut bytes {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            *byte = seed as u8;
        }
        check(&bytes, seed as usize % 8);
    }
}
