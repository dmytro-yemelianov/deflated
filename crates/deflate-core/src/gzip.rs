//! gzip framing (RFC 1952).
//!
//! `spec/Deflate/Gzip.lean` models minimal-header, single-member framing
//! with CRC32/ISIZE checks. Optional headers and concatenated members are
//! outside that model. Rust correspondence is tested, not proved; see
//! `docs/verification-boundary.md`.
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
    let mut out = Vec::new();
    gunzip_into(input, &mut out, limit)?;
    Ok(out)
}

/// Decode all gzip members into a reusable buffer with a cumulative limit.
///
/// Replaces the contents of `out`, reusing its allocation for the first member.
/// On error the buffer is empty. Every member's checksum and size are checked;
/// member history is isolated. Optional headers, concatenated members and final
/// zero padding have the same behavior as [`gunzip`]. The returned size equals
/// `out.len()`. This API consumes the whole input and is not streaming.
pub fn gunzip_into(input: &[u8], out: &mut Vec<u8>, limit: usize) -> Result<usize, Error> {
    gunzip_reusing(
        input,
        out,
        &mut Vec::new(),
        limit,
        crate::inflate::decode_into,
    )
}

pub(crate) fn gunzip_reusing(
    input: &[u8],
    out: &mut Vec<u8>,
    member: &mut Vec<u8>,
    limit: usize,
    decode: impl FnMut(&mut BitReader<'_>, &mut Vec<u8>, usize) -> Result<(), Error>,
) -> Result<usize, Error> {
    gunzip_reusing_with_crc32(input, out, member, limit, decode, Crc32::compute)
}

pub(crate) fn gunzip_reusing_with_crc32(
    input: &[u8],
    out: &mut Vec<u8>,
    member: &mut Vec<u8>,
    limit: usize,
    decode: impl FnMut(&mut BitReader<'_>, &mut Vec<u8>, usize) -> Result<(), Error>,
    crc32: impl FnMut(&[u8]) -> u32,
) -> Result<usize, Error> {
    out.clear();
    core::mem::swap(out, member);
    out.clear();
    member.clear();
    let result = decode_members(input, out, member, limit, decode, crc32);
    if let Err(error) = result {
        if member.capacity() > out.capacity() {
            core::mem::swap(out, member);
        }
        out.clear();
        member.clear();
        return Err(error);
    }
    member.clear();
    Ok(out.len())
}

// Decompression needs the boundary, not owned header metadata. Inspect a
// byte-aligned header without committing input; malformed or unaligned headers
// use the public parser so error precedence and reader position stay exact.
fn skip_gzip_header(r: &mut BitReader<'_>) -> Result<(), Error> {
    if r.bit_pos() % 8 == 0 {
        if let Some(header) = r.byte_window().first_chunk::<10>() {
            if header[..3] == [0x1f, 0x8b, 8] && header[3] & 0xe0 == 0 {
                if header[3] & !1 == 0 {
                    r.skip_bits(80);
                    return Ok(());
                }
                if let Some(bits) = optional_header_len(r.byte_window(), header[3])
                    .and_then(|bytes| bytes.checked_mul(8))
                    .filter(|&bits| bits <= r.bit_len().saturating_sub(r.bit_pos()))
                {
                    r.skip_bits(bits);
                    return Ok(());
                }
            }
        }
    }
    read_gzip_header(r).map(|_| ())
}

// The caller has checked the fixed ten-byte prefix and reserved flags. Keep
// optional-field scanning and checksum setup off the common minimal-header path.
#[inline(never)]
fn optional_header_len(input: &[u8], flags: u8) -> Option<usize> {
    let mut end = 10usize;
    if flags & 4 != 0 {
        let bytes = input.get(end..)?.first_chunk::<2>()?;
        let len = u16::from_le_bytes(*bytes) as usize;
        end += 2;
        end = end.checked_add(len)?;
        input.get(..end)?;
    }
    for flag in [8, 16] {
        if flags & flag != 0 {
            let len = input.get(end..)?.iter().position(|&byte| byte == 0)?;
            end = end.checked_add(len + 1)?;
        }
    }
    if flags & 2 != 0 {
        let expected = u16::from_le_bytes(*input.get(end..)?.first_chunk::<2>()?);
        if Crc32::compute(&input[..end]) as u16 != expected {
            return None;
        }
        end += 2;
    }
    Some(end)
}

fn decode_members(
    input: &[u8],
    out: &mut Vec<u8>,
    member: &mut Vec<u8>,
    limit: usize,
    mut decode: impl FnMut(&mut BitReader<'_>, &mut Vec<u8>, usize) -> Result<(), Error>,
    mut crc32: impl FnMut(&[u8]) -> u32,
) -> Result<(), Error> {
    let mut offset = 0;
    loop {
        let mut r = BitReader::new(&input[offset..]);
        skip_gzip_header(&mut r)?;
        // Reuse scratch space, but never history, between members.
        member.clear();
        let member_limit = limit.saturating_sub(out.len());
        decode(&mut r, member, member_limit)?;
        r.align_to_byte();
        let (expected_crc, expected_size) = read_gzip_trailer(&mut r)?;
        if crc32(member) != expected_crc {
            return Err(Error::InvalidHuffmanTree);
        }
        if member.len() as u32 != expected_size {
            return Err(Error::InvalidStoredLength);
        }
        offset += r.bit_pos() / 8;
        if out.is_empty() {
            core::mem::swap(out, member);
        } else {
            out.extend_from_slice(member);
        }
        let tail = &input[offset..];
        if tail.is_empty() || tail.iter().all(|&b| b == 0) {
            return Ok(());
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

    fn compare_header_skip(input: &[u8], offset: usize) {
        let mut fast = BitReader::new(input);
        let mut reference = BitReader::new(input);
        fast.skip_bits(offset);
        reference.skip_bits(offset);
        assert_eq!(
            (skip_gzip_header(&mut fast), fast.bit_pos()),
            (
                read_gzip_header(&mut reference).map(|_| ()),
                reference.bit_pos()
            ),
            "offset={offset}, input={input:?}"
        );
    }

    #[test]
    fn skipped_headers_preserve_public_parser_errors_and_positions() {
        for flags in 0..32 {
            for size in [0, 3, 31] {
                let extra: Vec<u8> = (0..size).map(|i| (i * 71) as u8).collect();
                let name = alloc::vec![b'n'; size];
                let comment = alloc::vec![b'c'; size];
                for offset in 0..8 {
                    let mut writer = BitWriter::new();
                    writer.write_bits(0x55, offset);
                    write_gzip_header(
                        &mut writer,
                        GzipFlags::from_byte(flags),
                        0xdeadbeef,
                        2,
                        255,
                        Some(&extra),
                        Some(&name),
                        Some(&comment),
                    );
                    let input = writer.finish();
                    for end in 0..=input.len() {
                        compare_header_skip(&input[..end], offset as usize);
                    }
                    if offset == 0 {
                        for index in 0..input.len() {
                            let mut changed = input.clone();
                            changed[index] ^= 0x80;
                            compare_header_skip(&changed, 0);
                        }
                    }
                }
            }
        }
        let minimal = [0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 255];
        for index in 0..minimal.len() {
            for byte in 0..=255 {
                let mut changed = minimal;
                changed[index] = byte;
                compare_header_skip(&changed, 0);
            }
        }
    }

    #[test]
    fn skipped_large_optional_fields_and_past_end_positions_match() {
        let extra = alloc::vec![0xa5; 65535];
        let name = alloc::vec![b'x'; 8192];
        let mut writer = BitWriter::new();
        write_gzip_header(
            &mut writer,
            GzipFlags::from_byte(31),
            123,
            0,
            3,
            Some(&extra),
            Some(&name),
            Some(&name),
        );
        let input = writer.finish();
        for end in [
            0,
            10,
            11,
            12,
            65546,
            65547,
            input.len() - 2,
            input.len() - 1,
            input.len(),
        ] {
            compare_header_skip(&input[..end], 0);
        }
        for offset in [
            input.len() * 8,
            input.len() * 8 + 8,
            usize::MAX - 7,
            usize::MAX,
        ] {
            compare_header_skip(&input, offset);
        }
    }

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
