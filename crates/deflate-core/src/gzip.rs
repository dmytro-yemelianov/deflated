//! gzip framing (RFC 1952).
//!
//! This is outside the Lean verification boundary (spec §6). The Lean model
//! in `spec/Deflate/` covers raw DEFLATE (RFC 1951) only. gzip adds a
//! header, optional extra fields, the DEFLATE stream, and a trailer with
//! CRC32 and ISIZE.
//!
//! The API mirrors the raw DEFLATE API but operates on gzip streams.

use crate::bitstream::BitReader;
use crate::bitwriter::BitWriter;
use crate::compress::deflate;
use crate::crc32::Crc32;
use crate::error::Error;
#[cfg(test)]
use crate::inflate::DEFAULT_LIMIT;
use alloc::vec::Vec;

/// Gzip header flags (RFC 1952 §2.3.1.1).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct GzipFlags {
    pub ftext: bool,    // bit 0
    pub fhcrc: bool,    // bit 1
    pub fextra: bool,   // bit 2
    pub fname: bool,    // bit 3
    pub fcomment: bool, // bit 4
}

impl GzipFlags {
    fn from_byte(b: u8) -> Self {
        GzipFlags {
            ftext: b & 0x01 != 0,
            fhcrc: b & 0x02 != 0,
            fextra: b & 0x04 != 0,
            fname: b & 0x08 != 0,
            fcomment: b & 0x10 != 0,
        }
    }

    fn to_byte(self) -> u8 {
        (self.ftext as u8)
            | ((self.fhcrc as u8) << 1)
            | ((self.fextra as u8) << 2)
            | ((self.fname as u8) << 3)
            | ((self.fcomment as u8) << 4)
    }
}

/// Parsed gzip header (RFC 1952 §2.1, §2.3).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GzipHeader {
    pub compression_method: u8, // CM = 8 (deflate)
    pub flags: GzipFlags,
    pub mtime: u32,                // Modification time (UNIX timestamp)
    pub xfl: u8,                   // Extra flags
    pub os: u8,                    // Operating system
    pub extra: Option<Vec<u8>>,    // FEXTRA field
    pub name: Option<Vec<u8>>,     // FNAME field (null-terminated)
    pub comment: Option<Vec<u8>>,  // FCOMMENT field (null-terminated)
    pub header_crc16: Option<u16>, // FHCRC field
}

// Header fields are whole bytes; hash the exact bytes as they are consumed.
fn read_header_bits(r: &mut BitReader<'_>, crc: &mut Crc32, n: u32) -> Result<u32, Error> {
    let value = r.read_bits(n)?;
    crc.update(&value.to_le_bytes()[..(n / 8) as usize]);
    Ok(value)
}

/// Read a null-terminated string from the reader.
fn read_null_terminated(r: &mut BitReader<'_>, crc: &mut Crc32) -> Result<Vec<u8>, Error> {
    let mut out = Vec::new();
    loop {
        let b = read_header_bits(r, crc, 8)? as u8;
        if b == 0 {
            break;
        }
        out.push(b);
    }
    Ok(out)
}

/// Write a null-terminated string to the writer.
fn write_null_terminated(w: &mut BitWriter, data: &[u8]) {
    for &b in data {
        w.write_bits(b as u32, 8);
    }
    w.write_bits(0, 8);
}

/// Parse the gzip header (RFC 1952 §2.1, §2.3).
pub fn read_gzip_header(r: &mut BitReader<'_>) -> Result<GzipHeader, Error> {
    let mut crc = Crc32::new();
    // ID1 (0x1f), ID2 (0x8b)
    let id1 = read_header_bits(r, &mut crc, 8)? as u8;
    let id2 = read_header_bits(r, &mut crc, 8)? as u8;
    if id1 != 0x1f || id2 != 0x8b {
        return Err(Error::InvalidBlockType); // Reuse for invalid gzip magic
    }

    // CM (compression method)
    let cm = read_header_bits(r, &mut crc, 8)? as u8;
    if cm != 8 {
        return Err(Error::InvalidBlockType); // Only deflate supported
    }

    // FLG
    let flg = read_header_bits(r, &mut crc, 8)? as u8;
    if flg & 0xe0 != 0 {
        return Err(Error::InvalidBlockType);
    }
    let flags = GzipFlags::from_byte(flg);

    // MTIME (4 bytes, little-endian)
    let mtime = read_header_bits(r, &mut crc, 32)?;

    // XFL
    let xfl = read_header_bits(r, &mut crc, 8)? as u8;

    // OS
    let os = read_header_bits(r, &mut crc, 8)? as u8;

    // Optional fields
    let mut extra = None;
    let mut name = None;
    let mut comment = None;
    let mut header_crc16 = None;

    if flags.fextra {
        let xlen = read_header_bits(r, &mut crc, 16)? as usize;
        let mut data = Vec::with_capacity(xlen);
        for _ in 0..xlen {
            data.push(read_header_bits(r, &mut crc, 8)? as u8);
        }
        extra = Some(data);
    }

    if flags.fname {
        name = Some(read_null_terminated(r, &mut crc)?);
    }

    if flags.fcomment {
        comment = Some(read_null_terminated(r, &mut crc)?);
    }

    if flags.fhcrc {
        let expected = r.read_bits(16)? as u16;
        if expected != crc.finalize() as u16 {
            return Err(Error::InvalidHuffmanTree);
        }
        header_crc16 = Some(expected);
    }

    Ok(GzipHeader {
        compression_method: cm,
        flags,
        mtime,
        xfl,
        os,
        extra,
        name,
        comment,
        header_crc16,
    })
}

/// Write a gzip header (RFC 1952 §2.1, §2.3).
#[allow(clippy::too_many_arguments)] // Public framing API mirrors the gzip header fields.
pub fn write_gzip_header(
    w: &mut BitWriter,
    flags: GzipFlags,
    mtime: u32,
    xfl: u8,
    os: u8,
    extra: Option<&[u8]>,
    name: Option<&[u8]>,
    comment: Option<&[u8]>,
) {
    let mut header = BitWriter::new();
    let destination = w;
    let w = &mut header;
    // ID1, ID2
    w.write_bits(0x1f, 8);
    w.write_bits(0x8b, 8);
    // CM = 8 (deflate)
    w.write_bits(8, 8);
    // FLG
    w.write_bits(flags.to_byte() as u32, 8);
    // MTIME (little-endian)
    w.write_bits(mtime, 32);
    // XFL
    w.write_bits(xfl as u32, 8);
    // OS
    w.write_bits(os as u32, 8);

    if flags.fextra {
        if let Some(extra_data) = extra {
            w.write_bits(extra_data.len() as u32, 16);
            for &b in extra_data {
                w.write_bits(b as u32, 8);
            }
        } else {
            w.write_bits(0, 16);
        }
    }

    if flags.fname {
        if let Some(name_data) = name {
            write_null_terminated(w, name_data);
        } else {
            w.write_bits(0, 8);
        }
    }

    if flags.fcomment {
        if let Some(comment_data) = comment {
            write_null_terminated(w, comment_data);
        } else {
            w.write_bits(0, 8);
        }
    }

    let bytes = header.finish();
    for &byte in &bytes {
        destination.write_bits(byte as u32, 8);
    }
    if flags.fhcrc {
        destination.write_bits(Crc32::compute(&bytes) & 0xffff, 16);
    }
}

/// Read gzip trailer (RFC 1952 §2.2): CRC32 + ISIZE.
pub fn read_gzip_trailer(r: &mut BitReader<'_>) -> Result<(u32, u32), Error> {
    let crc32 = r.read_bits(32)?;
    let isize = r.read_bits(32)?;
    Ok((crc32, isize))
}

/// Write gzip trailer (RFC 1952 §2.2): CRC32 + ISIZE.
pub fn write_gzip_trailer(w: &mut BitWriter, crc32: u32, isize: u32) {
    w.write_bits(crc32, 32);
    w.write_bits(isize, 32);
}

/// Decompress all members of a gzip stream with a cumulative output limit.
/// Trailing zero padding is accepted; other trailing bytes (including a member
/// after padding) are rejected. Every member's header and trailer are validated.
pub fn gunzip(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut offset = 0;
    let mut out = Vec::new();
    loop {
        let mut r = BitReader::new(&input[offset..]);
        read_gzip_header(&mut r)?;
        // A fresh buffer prevents backreferences across member boundaries.
        let mut member = Vec::new();
        let member_limit = limit.saturating_sub(out.len());
        loop {
            let header = crate::block::read_block_header(&mut r)?;
            match header.btype {
                crate::block::BlockType::Stored => {
                    let budget = member_limit.saturating_sub(member.len());
                    crate::block::read_stored(&mut r, &mut member, budget)?;
                }
                crate::block::BlockType::Fixed => {
                    let lit = crate::huffman::fixed_litlen();
                    let dst = crate::huffman::fixed_dist();
                    crate::block::decode_huff_block(&lit, &dst, &mut r, &mut member, member_limit)?;
                }
                crate::block::BlockType::Dynamic => {
                    let (lit, dst) = crate::block::read_dynamic_tables(&mut r)?;
                    crate::block::decode_huff_block(&lit, &dst, &mut r, &mut member, member_limit)?;
                }
            }
            if header.is_final {
                break;
            }
        }
        r.align_to_byte();
        let (expected_crc, expected_size) = read_gzip_trailer(&mut r)?;
        if Crc32::compute(&member) != expected_crc {
            return Err(Error::InvalidHuffmanTree);
        }
        if member.len() as u32 != expected_size {
            return Err(Error::InvalidStoredLength);
        }
        offset += r.bit_pos() / 8;
        out.extend_from_slice(&member);
        let tail = &input[offset..];
        if tail.is_empty() || tail.iter().all(|&b| b == 0) {
            return Ok(out);
        }
        // Any non-padding tail must parse as another complete member.
    }
}

/// Compress data into a gzip stream.
pub fn gzip(input: &[u8], _limit: usize) -> Result<Vec<u8>, Error> {
    Ok(frame_gzip(input, &deflate(input)))
}

/// Compress data into gzip using stored DEFLATE blocks only.
/// As with `gzip`, `limit` is retained for API symmetry, not compression limits.
pub fn gzip_stored(input: &[u8], _limit: usize) -> Result<Vec<u8>, Error> {
    Ok(frame_gzip(input, &crate::deflate_stored(input)))
}

fn frame_gzip(input: &[u8], deflate_data: &[u8]) -> Vec<u8> {
    let mut w = BitWriter::new();

    // Write gzip header (minimal: no optional fields)
    let flags = GzipFlags {
        ftext: false,
        fhcrc: false,
        fextra: false,
        fname: false,
        fcomment: false,
    };
    write_gzip_header(&mut w, flags, 0, 0, 255, None, None, None);

    // Write DEFLATE data
    for &b in deflate_data {
        w.write_bits(b as u32, 8);
    }

    // Compute CRC32 and ISIZE
    let mut crc = Crc32::new();
    crc.update(input);
    let crc32 = crc.finalize();
    let isize = input.len() as u32;

    // Write trailer
    write_gzip_trailer(&mut w, crc32, isize);

    w.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gzip_roundtrip_simple() {
        let data = b"hello world";
        let compressed = gzip(data, DEFAULT_LIMIT).unwrap();
        let decompressed = gunzip(&compressed, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
    }

    #[test]
    fn gzip_roundtrip_empty() {
        let data = b"";
        let compressed = gzip(data, DEFAULT_LIMIT).unwrap();
        let decompressed = gunzip(&compressed, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
    }

    #[test]
    fn gzip_roundtrip_larger() {
        let data = b"The quick brown fox jumps over the lazy dog. ".repeat(100);
        let compressed = gzip(&data, DEFAULT_LIMIT).unwrap();
        let decompressed = gunzip(&compressed, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
    }
}
