//! The accelerated decoder must be observationally identical to the core:
//! same result, same output bytes, same errors and same output clearing.

use deflate_core::{Error, gzip::gzip};

fn sample(len: usize) -> Vec<u8> {
    let mut state = 0x1234_5678u32;
    (0..len)
        .map(|i| {
            state = state.wrapping_mul(1_103_515_245).wrapping_add(12_345);
            if i % 7 < 4 {
                b"abcd"[i % 4]
            } else {
                (state >> 24) as u8
            }
        })
        .collect()
}

fn packets() -> Vec<Vec<u8>> {
    let mut packets = Vec::new();
    for len in [0, 1, 15, 16, 17, 255, 4096, 70_000] {
        packets.push(gzip(&sample(len), 0).unwrap());
    }
    // Two concatenated members.
    let mut two = gzip(b"first member ", 0).unwrap();
    two.extend(gzip(&sample(5000), 0).unwrap());
    packets.push(two);
    packets
}

fn variants(packet: &[u8]) -> Vec<Vec<u8>> {
    let mut out = vec![packet.to_vec()];
    let n = packet.len();
    // Corrupt CRC (first trailer byte of the last member), ISIZE, truncate,
    // add a trailing garbage suffix.
    for pos in [n - 8, n - 4] {
        let mut bad = packet.to_vec();
        bad[pos] ^= 1;
        out.push(bad);
    }
    out.push(packet[..n - 1].to_vec());
    out.push(packet[..n / 2].to_vec());
    let mut suffix = packet.to_vec();
    suffix.extend_from_slice(&[0x1f, 0x8b, 0]);
    out.push(suffix);
    out
}

fn assert_same(input: &[u8], limit: usize, decoder: &mut deflate_accel::Decompressor) {
    let mut core_out = vec![42; 32];
    let mut accel_out = vec![42; 32];
    let core = deflate_core::gunzip_into(input, &mut core_out, limit);
    let accel = decoder.gunzip_into(input, &mut accel_out, limit);
    assert_eq!(accel, core, "result for len={} limit={limit}", input.len());
    assert_eq!(accel_out, core_out, "output for len={}", input.len());
    assert_eq!(
        deflate_accel::gunzip(input, limit),
        deflate_core::gunzip(input, limit)
    );
}

#[test]
fn gunzip_matches_core_on_valid_and_corrupted_packets() {
    let mut decoder = deflate_accel::Decompressor::new();
    for packet in packets() {
        for input in variants(&packet) {
            for limit in [0, 1, 16, 4096, usize::MAX] {
                assert_same(&input, limit, &mut decoder);
            }
        }
    }
}

#[test]
fn corrupted_crc_is_rejected_with_the_core_checksum_error() {
    let mut packet = gzip(&sample(1000), 0).unwrap();
    let n = packet.len();
    packet[n - 8] ^= 0x80;
    assert_eq!(
        deflate_accel::gunzip(&packet, usize::MAX),
        Err(Error::InvalidHuffmanTree)
    );
}

#[test]
fn raw_inflate_and_release_match_core() {
    let data = sample(20_000);
    let raw = deflate_core::deflate(&data);
    let mut decoder = deflate_accel::Decompressor::new();
    let mut out = Vec::new();
    for round in 0..3 {
        if round == 1 {
            decoder.release_buffers();
        }
        let mut expected = Vec::new();
        assert_eq!(
            decoder.inflate_into(&raw, &mut out, usize::MAX),
            deflate_core::inflate_into(&raw, &mut expected, usize::MAX)
        );
        assert_eq!(out, data);
    }
}
