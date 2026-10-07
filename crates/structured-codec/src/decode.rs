use crate::wire::{Cursor, Error, check};
use alloc::vec::Vec;
use deflate_core::bitstream::BitReader;
use deflate_core::block::{
    BlockType, decode_huff_block, read_block_header, read_dynamic_tables, read_stored,
};
use deflate_core::huffman::{fixed_dist, fixed_litlen};

pub const DEFAULT_LIMIT: usize = 64 << 20;

pub fn decode(packet: &[u8]) -> Result<Vec<u8>, Error> {
    decode_with_limit(packet, DEFAULT_LIMIT)
}

// Separate driver: the core decoder's deliberate suffix semantics are unchanged.
fn strict_inflate(packet: &[u8], expected: usize) -> Result<Vec<u8>, Error> {
    let mut reader = BitReader::new(packet);
    let mut out = Vec::new();
    let driver = (|| {
        loop {
            let header = read_block_header(&mut reader)?;
            match header.btype {
                BlockType::Stored => {
                    let budget = expected.saturating_sub(out.len());
                    read_stored(&mut reader, &mut out, budget)?;
                }
                BlockType::Fixed => decode_huff_block(
                    &fixed_litlen(),
                    &fixed_dist(),
                    &mut reader,
                    &mut out,
                    expected,
                )?,
                BlockType::Dynamic => {
                    let (lit, dst) = read_dynamic_tables(&mut reader)?;
                    decode_huff_block(&lit, &dst, &mut reader, &mut out, expected)?;
                }
            }
            if header.is_final {
                return Ok::<(), deflate_core::Error>(());
            }
        }
    })();
    driver.map_err(|error| {
        if error == deflate_core::Error::OutputLimitExceeded {
            Error::InvalidLength
        } else {
            Error::DeflateError
        }
    })?;
    check(
        reader.bit_pos().div_ceil(8) == packet.len(),
        Error::TrailingData,
    )?;
    check(out.len() == expected, Error::InvalidLength)?;
    Ok(out)
}

fn read_dictionary(data: &[u8]) -> Result<Vec<&[u8]>, Error> {
    let mut cursor = Cursor::new(data);
    let count = cursor.varint()?;
    check(count <= 256, Error::InvalidLength)?;
    let mut entries = Vec::new();
    for _ in 0..count {
        let length = cursor.varint()?;
        check((1..=256).contains(&length), Error::InvalidLength)?;
        let entry = cursor.take(length as usize)?;
        check(!entries.contains(&entry), Error::DuplicateDictionary)?;
        entries.push(entry);
    }
    check(cursor.remaining() == 0, Error::UnusedSubstream)?;
    Ok(entries)
}

pub(crate) fn expand(streams: &[Vec<u8>; 4], expected: usize) -> Result<Vec<u8>, Error> {
    let entries = read_dictionary(&streams[0])?;
    let mut ops = Cursor::new(&streams[1]);
    let mut literals = Cursor::new(&streams[2]);
    let mut numbers = Cursor::new(&streams[3]);
    let mut out = Vec::new();
    let mut previous = None;
    while ops.remaining() != 0 {
        match ops.byte()? {
            0 => {
                let length = ops.varint()?;
                check(
                    length > 0 && length <= (expected - out.len()) as u64,
                    Error::InvalidLength,
                )?;
                out.extend_from_slice(literals.take(length as usize)?);
            }
            1 => {
                let id = ops.varint()?;
                check(id < entries.len() as u64, Error::BadDictionaryId)?;
                let entry = entries[id as usize];
                check(entry.len() <= expected - out.len(), Error::InvalidLength)?;
                out.extend_from_slice(entry);
            }
            opcode @ (2 | 3) => {
                if opcode == 3 {
                    check(previous.is_some(), Error::MissingNumericBase)?;
                }
                let encoded = numbers.varint()?;
                let value = if opcode == 2 {
                    encoded
                } else {
                    let delta = if encoded & 1 == 0 {
                        i128::from(encoded / 2)
                    } else {
                        -i128::from(encoded / 2) - 1
                    };
                    let value = i128::from(previous.ok_or(Error::MissingNumericBase)?) + delta;
                    check(
                        (0..=i128::from(u64::MAX)).contains(&value),
                        Error::IntegerOverflow,
                    )?;
                    value as u64
                };
                previous = Some(value);
                // At most 20 bytes, no locale, float or semantic JSON rendering.
                let mut digits = [0_u8; 20];
                let mut start = digits.len();
                let mut rest = value;
                loop {
                    start -= 1;
                    digits[start] = b'0' + (rest % 10) as u8;
                    rest /= 10;
                    if rest == 0 {
                        break;
                    }
                }
                check(
                    digits.len() - start <= expected - out.len(),
                    Error::InvalidLength,
                )?;
                out.extend_from_slice(&digits[start..]);
            }
            _ => return Err(Error::BadOpcode),
        }
    }
    check(out.len() == expected, Error::InvalidLength)?;
    check(
        literals.remaining() == 0 && numbers.remaining() == 0,
        Error::UnusedSubstream,
    )?;
    Ok(out)
}

fn split_decode(payload: &[u8], expected: usize) -> Result<Vec<u8>, Error> {
    let mut cursor = Cursor::new(payload);
    let mut descriptors = [(0, 0, 0); 4];
    for (descriptor, cap) in
        descriptors
            .iter_mut()
            .zip([65536, 4 * expected, 4 * expected, 4 * expected])
    {
        let raw = cursor.u32()? as usize;
        let stored = cursor.u32()? as usize;
        let storage = cursor.byte()?;
        check(cursor.take(3)? == [0, 0, 0], Error::BadFlags)?;
        check(storage <= 1, Error::BadStorage)?;
        check(raw <= cap && stored <= cap + 64, Error::InvalidLength)?;
        check(raw != 0 || (storage == 0 && stored == 0), Error::BadStorage)?;
        check(storage != 0 || raw == stored, Error::InvalidLength)?;
        *descriptor = (raw, stored, storage);
    }
    check(
        descriptors.iter().map(|d| d.0).sum::<usize>() <= 8 * expected + 65536,
        Error::InvalidLength,
    )?;
    check(
        descriptors.iter().map(|d| d.1).sum::<usize>() == cursor.remaining(),
        Error::InvalidLength,
    )?;
    let mut streams = [Vec::new(), Vec::new(), Vec::new(), Vec::new()];
    for (stream, (raw, stored, storage)) in streams.iter_mut().zip(descriptors) {
        let bytes = cursor.take(stored)?;
        *stream = if storage == 0 {
            bytes.to_vec()
        } else {
            strict_inflate(bytes, raw)?
        };
    }
    expand(&streams, expected)
}

pub fn decode_with_limit(packet: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut cursor = Cursor::new(packet);
    // Header must be complete before semantic validation, matching the oracle.
    let header = cursor.take(24)?;
    let mut fields = Cursor::new(header);
    let magic = fields.take(4)?;
    let version = fields.byte()?;
    let log2 = fields.byte()?;
    let reserved = fields.u16()?;
    let total = fields.u64()?;
    let count = fields.u32()?;
    let checksum = fields.u32()?;
    check(magic == b"DSC1", Error::BadMagic)?;
    check(version == 1, Error::UnsupportedVersion)?;
    check(reserved == 0, Error::BadFlags)?;
    check(log2 == 16 || log2 == 18, Error::InvalidLength)?;
    check(total <= limit as u64, Error::OutputLimit)?;
    let chunk_size = 1_u64 << log2;
    check(
        u64::from(count) == total.div_ceil(chunk_size),
        Error::BadChunkCount,
    )?;
    let mut out = Vec::new();
    for index in 0..count {
        let mut fields = Cursor::new(cursor.take(16)?);
        let mode = fields.byte()?;
        let flags = fields.byte()?;
        let reserved = fields.u16()?;
        let raw = fields.u32()? as usize;
        let stored = fields.u32()? as usize;
        let chunk_crc = fields.u32()?;
        check(flags == 0 && reserved == 0, Error::BadFlags)?;
        check(mode <= 2, Error::BadStorage)?;
        check(
            raw as u64 == chunk_size.min(total - u64::from(index) * chunk_size),
            Error::InvalidLength,
        )?;
        check(stored <= 8 * raw + 65536 + 304, Error::InvalidLength)?;
        check(mode != 0 || stored == raw, Error::InvalidLength)?;
        let payload = cursor.take(stored)?;
        let chunk = match mode {
            0 => payload.to_vec(),
            1 => strict_inflate(payload, raw)?,
            _ => split_decode(payload, raw)?,
        };
        check(
            deflate_core::crc32::Crc32::compute(&chunk) == chunk_crc,
            Error::ChecksumMismatch,
        )?;
        out.extend_from_slice(&chunk);
    }
    check(cursor.remaining() == 0, Error::TrailingData)?;
    check(
        deflate_core::crc32::Crc32::compute(&out) == checksum,
        Error::ChecksumMismatch,
    )?;
    Ok(out)
}
