use deflate_core::bitstream::BitReader;
use deflate_core::bitwriter::BitWriter;
use deflate_core::crc32::Crc32;
use deflate_core::gzip::{GzipFlags, gunzip, gzip, read_gzip_header, write_gzip_header};
use deflate_core::{Error, encode_fixed::emit_fixed, tokens::Token};
use std::io::Write;
use std::process::{Command, Stdio};

fn pair() -> Vec<u8> {
    [gzip(b"first", 100).unwrap(), gzip(b"second", 100).unwrap()].concat()
}

#[test]
fn concatenation_and_cumulative_limit() {
    assert_eq!(gunzip(&pair(), 11).unwrap(), b"firstsecond");
    assert_eq!(gunzip(&pair(), 10), Err(Error::OutputLimitExceeded));
    assert_eq!(gunzip(&gzip(b"", 0).unwrap(), 0).unwrap(), b"");
}

#[test]
fn later_member_errors_and_padding() {
    let bytes = pair();
    for end in gzip(b"first", 100).unwrap().len() + 1..bytes.len() {
        assert!(gunzip(&bytes[..end], 100).is_err(), "truncation at {end}");
    }
    for offset in [bytes.len() - 8, bytes.len() - 4] {
        let mut bad = bytes.clone();
        bad[offset] ^= 1;
        assert!(gunzip(&bad, 100).is_err());
    }
    let mut padded = bytes.clone();
    padded.extend_from_slice(&[0; 8]);
    assert_eq!(gunzip(&padded, 100).unwrap(), b"firstsecond");
    padded.push(1);
    assert!(gunzip(&padded, 100).is_err());
    let mut separated = gzip(b"first", 100).unwrap();
    separated.push(0);
    separated.extend(gzip(b"second", 100).unwrap());
    assert!(gunzip(&separated, 100).is_err());
}

#[test]
fn history_is_reset_between_members() {
    let mut bytes = gzip(b"abc", 100).unwrap();
    let mut second = gzip(b"", 100).unwrap()[..10].to_vec();
    second.extend(emit_fixed([Token::Match { len: 3, dist: 3 }]));
    second.extend(Crc32::compute(b"abc").to_le_bytes());
    second.extend(3u32.to_le_bytes());
    bytes.extend(second);
    assert_eq!(gunzip(&bytes, 100), Err(Error::InvalidDistance));
}

fn optional_header() -> Vec<u8> {
    let mut w = BitWriter::new();
    write_gzip_header(
        &mut w,
        GzipFlags {
            ftext: true,
            fhcrc: true,
            fextra: true,
            fname: true,
            fcomment: true,
        },
        1234,
        0,
        255,
        Some(b"extra"),
        Some(b"name"),
        Some(b"comment"),
    );
    w.finish()
}

#[test]
fn header_crc_validation_and_zlib_acceptance() {
    let header = optional_header();
    let end = header.len() - 2;
    assert_eq!(
        u16::from_le_bytes(header[end..].try_into().unwrap()),
        Crc32::compute(&header[..end]) as u16
    );
    assert!(read_gzip_header(&mut BitReader::new(&header)).is_ok());
    let mut bytes = header.clone();
    bytes.extend_from_slice(&gzip(b"X", 100).unwrap()[10..]);
    assert_eq!(gunzip(&bytes, 100).unwrap(), b"X");
    let mut child = Command::new("python3")
        .args([
            "-c",
            "import sys,zlib; assert zlib.decompress(sys.stdin.buffer.read(),31)==b'X'",
        ])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(&bytes).unwrap();
    assert!(child.wait().unwrap().success());
    for offset in [4, end] {
        let mut bad = bytes.clone();
        bad[offset] ^= 1;
        assert_eq!(gunzip(&bad, 100), Err(Error::InvalidHuffmanTree));
        assert!(read_gzip_header(&mut BitReader::new(&bad)).is_err());
    }
    for offset in [0, 2, 3] {
        let mut bad = bytes.clone();
        bad[offset] |= 0x80;
        assert!(gunzip(&bad, 100).is_err());
    }
    for end in 0..header.len() {
        assert!(read_gzip_header(&mut BitReader::new(&header[..end])).is_err());
    }
}
