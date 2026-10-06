//! ZIP container (RFC 1951 DEFLATE + ZIP format).
//!
//! `spec/Deflate/Zip.lean` models canonical single-entry STORED archives.
//! DEFLATE entries, descriptors and general metadata are outside that model.
//! Rust correspondence is tested, not proved; see `docs/verification-boundary.md`.
//!
//! Minimal implementation: extract or create one stored or DEFLATE entry.

use crate::bitwriter::BitWriter;
use crate::compress::deflate;
use crate::crc32::Crc32;
use crate::error::Error;
#[cfg(test)]
use crate::inflate::DEFAULT_LIMIT;
use crate::inflate::inflate_with_limit;
use alloc::vec::Vec;

/// ZIP local file header signature (0x04034b50).
const LOCAL_FILE_HEADER_SIG: u32 = 0x04034b50;
/// ZIP central directory header signature (0x02014b50).
const CENTRAL_DIR_HEADER_SIG: u32 = 0x02014b50;
/// ZIP end of central directory signature (0x06054b50).
const END_CENTRAL_DIR_SIG: u32 = 0x06054b50;
/// ZIP data descriptor signature (0x08074b50).
const DATA_DESCRIPTOR_SIG: u32 = 0x08074b50;

/// Compression method: 0 = stored, 8 = deflate.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CompressionMethod {
    Stored = 0,
    Deflate = 8,
}

impl CompressionMethod {
    fn from_u16(v: u16) -> Result<Self, Error> {
        match v {
            0 => Ok(CompressionMethod::Stored),
            8 => Ok(CompressionMethod::Deflate),
            _ => Err(Error::InvalidBlockType),
        }
    }

    fn to_u16(self) -> u16 {
        self as u16
    }
}

/// ZIP local file header (RFC 1951 Appendix D, section 4.3.7).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocalFileHeader {
    pub version_needed: u16,
    pub general_purpose_flag: u16,
    pub compression_method: CompressionMethod,
    pub last_mod_time: u16,
    pub last_mod_date: u16,
    pub crc32: u32,
    pub compressed_size: u32,
    pub uncompressed_size: u32,
    pub file_name: Vec<u8>,
    pub extra_field: Vec<u8>,
}

/// ZIP central directory header (RFC 1951 Appendix D, section 4.3.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CentralDirHeader {
    pub version_made_by: u16,
    pub version_needed: u16,
    pub general_purpose_flag: u16,
    pub compression_method: CompressionMethod,
    pub last_mod_time: u16,
    pub last_mod_date: u16,
    pub crc32: u32,
    pub compressed_size: u32,
    pub uncompressed_size: u32,
    pub file_name: Vec<u8>,
    pub extra_field: Vec<u8>,
    pub file_comment: Vec<u8>,
    pub disk_number_start: u16,
    pub internal_attr: u16,
    pub external_attr: u32,
    pub local_header_offset: u32,
}

/// ZIP end of central directory record (RFC 1951 Appendix D, section 4.3.16).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EndCentralDir {
    pub disk_number: u16,
    pub disk_with_cd: u16,
    pub entries_on_disk: u16,
    pub total_entries: u16,
    pub cd_size: u32,
    pub cd_offset: u32,
    pub comment: Vec<u8>,
}

/// Read little-endian u16 from slice.
fn read_u16_le(data: &[u8], offset: usize) -> Result<u16, Error> {
    if offset + 2 > data.len() {
        return Err(Error::UnexpectedEof);
    }
    Ok(u16::from_le_bytes([data[offset], data[offset + 1]]))
}

/// Read little-endian u32 from slice.
fn read_u32_le(data: &[u8], offset: usize) -> Result<u32, Error> {
    if offset + 4 > data.len() {
        return Err(Error::UnexpectedEof);
    }
    Ok(u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]))
}

/// Write little-endian u16 to writer.
fn write_u16_le(w: &mut crate::bitwriter::BitWriter, v: u16) {
    w.write_bits(v as u32 & 0xFF, 8);
    w.write_bits((v as u32 >> 8) & 0xFF, 8);
}

/// Write little-endian u32 to writer.
fn write_u32_le(w: &mut crate::bitwriter::BitWriter, v: u32) {
    w.write_bits(v & 0xFF, 8);
    w.write_bits((v >> 8) & 0xFF, 8);
    w.write_bits((v >> 16) & 0xFF, 8);
    w.write_bits((v >> 24) & 0xFF, 8);
}

/// Parse local file header.
pub fn read_local_file_header(data: &[u8]) -> Result<(LocalFileHeader, usize), Error> {
    if data.len() < 30 {
        return Err(Error::UnexpectedEof);
    }
    let sig = read_u32_le(data, 0)?;
    if sig != LOCAL_FILE_HEADER_SIG {
        return Err(Error::InvalidBlockType);
    }
    let version_needed = read_u16_le(data, 4)?;
    let general_purpose_flag = read_u16_le(data, 6)?;
    let compression_method = CompressionMethod::from_u16(read_u16_le(data, 8)?)?;
    let last_mod_time = read_u16_le(data, 10)?;
    let last_mod_date = read_u16_le(data, 12)?;
    let crc32 = read_u32_le(data, 14)?;
    let compressed_size = read_u32_le(data, 18)?;
    let uncompressed_size = read_u32_le(data, 22)?;
    let file_name_len = read_u16_le(data, 26)? as usize;
    let extra_field_len = read_u16_le(data, 28)? as usize;

    let header_end = 30 + file_name_len + extra_field_len;
    if data.len() < header_end {
        return Err(Error::UnexpectedEof);
    }

    let file_name = data[30..30 + file_name_len].to_vec();
    let extra_field = data[30 + file_name_len..header_end].to_vec();

    Ok((
        LocalFileHeader {
            version_needed,
            general_purpose_flag,
            compression_method,
            last_mod_time,
            last_mod_date,
            crc32,
            compressed_size,
            uncompressed_size,
            file_name,
            extra_field,
        },
        header_end,
    ))
}

/// Parse central directory header.
pub fn read_central_dir_header(data: &[u8]) -> Result<(CentralDirHeader, usize), Error> {
    if data.len() < 46 {
        return Err(Error::UnexpectedEof);
    }
    let sig = read_u32_le(data, 0)?;
    if sig != CENTRAL_DIR_HEADER_SIG {
        return Err(Error::InvalidBlockType);
    }
    let version_made_by = read_u16_le(data, 4)?;
    let version_needed = read_u16_le(data, 6)?;
    let general_purpose_flag = read_u16_le(data, 8)?;
    let compression_method = CompressionMethod::from_u16(read_u16_le(data, 10)?)?;
    let last_mod_time = read_u16_le(data, 12)?;
    let last_mod_date = read_u16_le(data, 14)?;
    let crc32 = read_u32_le(data, 16)?;
    let compressed_size = read_u32_le(data, 20)?;
    let uncompressed_size = read_u32_le(data, 24)?;
    let file_name_len = read_u16_le(data, 28)? as usize;
    let extra_field_len = read_u16_le(data, 30)? as usize;
    let file_comment_len = read_u16_le(data, 32)? as usize;
    let disk_number_start = read_u16_le(data, 34)?;
    let internal_attr = read_u16_le(data, 36)?;
    let external_attr = read_u32_le(data, 38)?;
    let local_header_offset = read_u32_le(data, 42)?;

    let header_end = 46 + file_name_len + extra_field_len + file_comment_len;
    if data.len() < header_end {
        return Err(Error::UnexpectedEof);
    }

    let file_name = data[46..46 + file_name_len].to_vec();
    let extra_field = data[46 + file_name_len..46 + file_name_len + extra_field_len].to_vec();
    let file_comment = data[46 + file_name_len + extra_field_len..header_end].to_vec();

    Ok((
        CentralDirHeader {
            version_made_by,
            version_needed,
            general_purpose_flag,
            compression_method,
            last_mod_time,
            last_mod_date,
            crc32,
            compressed_size,
            uncompressed_size,
            file_name,
            extra_field,
            file_comment,
            disk_number_start,
            internal_attr,
            external_attr,
            local_header_offset,
        },
        header_end,
    ))
}

/// Parse end of central directory record.
pub fn read_end_central_dir(data: &[u8]) -> Result<EndCentralDir, Error> {
    if data.len() < 22 {
        return Err(Error::UnexpectedEof);
    }
    let sig = read_u32_le(data, 0)?;
    if sig != END_CENTRAL_DIR_SIG {
        return Err(Error::InvalidBlockType);
    }
    let disk_number = read_u16_le(data, 4)?;
    let disk_with_cd = read_u16_le(data, 6)?;
    let entries_on_disk = read_u16_le(data, 8)?;
    let total_entries = read_u16_le(data, 10)?;
    let cd_size = read_u32_le(data, 12)?;
    let cd_offset = read_u32_le(data, 16)?;
    let comment_len = read_u16_le(data, 20)? as usize;

    if data.len() < 22 + comment_len {
        return Err(Error::UnexpectedEof);
    }
    let comment = data[22..22 + comment_len].to_vec();

    Ok(EndCentralDir {
        disk_number,
        disk_with_cd,
        entries_on_disk,
        total_entries,
        cd_size,
        cd_offset,
        comment,
    })
}

/// Find end of central directory record by scanning from end.
pub fn find_end_central_dir(data: &[u8]) -> Option<usize> {
    if data.len() < 22 {
        return None;
    }
    // A comment is at most u16::MAX bytes. Inspect the nearest candidate first.
    let start = data.len().saturating_sub(22 + u16::MAX as usize);
    for offset in (start..=data.len() - 22).rev() {
        if read_u32_le(data, offset).ok()? != END_CENTRAL_DIR_SIG {
            continue;
        }
        let comment_len = read_u16_le(data, offset + 20).ok()? as usize;
        let cd_size = read_u32_le(data, offset + 12).ok()? as usize;
        let cd_offset = read_u32_le(data, offset + 16).ok()? as usize;
        if comment_len == data.len() - offset - 22 && cd_offset.checked_add(cd_size) == Some(offset)
        {
            return Some(offset);
        }
    }
    None
}

/// Extract a single DEFLATE-compressed entry from ZIP.
pub fn unzip_single(data: &[u8], limit: usize) -> Result<(Vec<u8>, Vec<u8>), Error> {
    let eocd_offset = find_end_central_dir(data).ok_or(Error::InvalidBlockType)?;
    let eocd_data = &data[eocd_offset..];
    // This API supports exactly one entry on one disk, without ZIP64.
    if read_u16_le(eocd_data, 4)? != 0
        || read_u16_le(eocd_data, 6)? != 0
        || read_u16_le(eocd_data, 8)? != 1
        || read_u16_le(eocd_data, 10)? != 1
    {
        return Err(Error::InvalidBlockType);
    }
    let cd_offset = read_u32_le(eocd_data, 16)? as usize;
    let cd_data = &data[cd_offset..eocd_offset];
    // Check the output size before parsing headers (which copy variable fields).
    let compressed_size = read_u32_le(cd_data, 20)?;
    let uncompressed_size = read_u32_le(cd_data, 24)?;
    if compressed_size == u32::MAX || uncompressed_size == u32::MAX {
        return Err(Error::InvalidStoredLength);
    }
    if uncompressed_size as usize > limit {
        return Err(Error::OutputLimitExceeded);
    }
    let (cd, cd_len) = read_central_dir_header(cd_data)?;
    // Bits 1/2 are compression-level hints for DEFLATE only.
    let allowed_flags = match cd.compression_method {
        CompressionMethod::Deflate => 0x080e,
        CompressionMethod::Stored => 0x0808,
    };
    if cd_len != cd_data.len()
        || cd.disk_number_start != 0
        || cd.general_purpose_flag & !allowed_flags != 0
    {
        return Err(Error::InvalidBlockType);
    }
    let lfh_offset = cd.local_header_offset as usize;
    let local_data = data
        .get(lfh_offset..cd_offset)
        .ok_or(Error::UnexpectedEof)?;
    let (lfh, lfh_size) = read_local_file_header(local_data)?;
    if lfh.file_name != cd.file_name
        || lfh.compression_method != cd.compression_method
        || lfh.general_purpose_flag != cd.general_purpose_flag
    {
        return Err(Error::InvalidBlockType);
    }
    let streamed = cd.general_purpose_flag & 8 != 0;
    if !streamed
        && (lfh.crc32 != cd.crc32
            || lfh.compressed_size != cd.compressed_size
            || lfh.uncompressed_size != cd.uncompressed_size)
    {
        return Err(Error::InvalidStoredLength);
    }
    let compressed_end = lfh_size
        .checked_add(cd.compressed_size as usize)
        .ok_or(Error::InvalidStoredLength)?;
    let compressed_data = local_data
        .get(lfh_size..compressed_end)
        .ok_or(Error::UnexpectedEof)?;
    let tail = &local_data[compressed_end..];
    if streamed {
        // Standard descriptors are 12 bytes, or 16 with the optional signature.
        let descriptor = match tail.len() {
            12 => tail,
            16 if read_u32_le(tail, 0)? == DATA_DESCRIPTOR_SIG => &tail[4..],
            _ => return Err(Error::InvalidStoredLength),
        };
        if read_u32_le(descriptor, 0)? != cd.crc32 {
            return Err(Error::InvalidHuffmanTree);
        }
        if read_u32_le(descriptor, 4)? != cd.compressed_size
            || read_u32_le(descriptor, 8)? != cd.uncompressed_size
        {
            return Err(Error::InvalidStoredLength);
        }
    } else if !tail.is_empty() {
        return Err(Error::InvalidStoredLength);
    }
    let decompressed = match cd.compression_method {
        CompressionMethod::Stored => {
            if cd.compressed_size != cd.uncompressed_size {
                return Err(Error::InvalidStoredLength);
            }
            compressed_data.to_vec()
        }
        CompressionMethod::Deflate => inflate_with_limit(compressed_data, limit)?,
    };
    if decompressed.len() != cd.uncompressed_size as usize {
        return Err(Error::InvalidStoredLength);
    }
    let mut crc = Crc32::new();
    crc.update(&decompressed);
    if crc.finalize() != cd.crc32 {
        return Err(Error::InvalidHuffmanTree);
    }
    Ok((decompressed, cd.file_name))
}

/// Create a ZIP archive with a single DEFLATE-compressed entry.
pub fn zip_single(
    file_name: &[u8],
    data: &[u8],
    compression: CompressionMethod,
) -> Result<Vec<u8>, Error> {
    let file_name_len = u16::try_from(file_name.len()).map_err(|_| Error::InvalidLength)?;
    let uncompressed_size = u32::try_from(data.len()).map_err(|_| Error::InvalidLength)?;
    // u32::MAX denotes ZIP64, which this minimal writer does not emit.
    if uncompressed_size == u32::MAX {
        return Err(Error::InvalidLength);
    }
    let mut w = BitWriter::new();

    // Compute CRC32 and sizes
    let mut crc = Crc32::new();
    crc.update(data);
    let crc32 = crc.finalize();

    let compressed_data = match compression {
        CompressionMethod::Stored => {
            // Stored: just the data
            data.to_vec()
        }
        CompressionMethod::Deflate => deflate(data),
    };
    let compressed_size = u32::try_from(compressed_data.len()).map_err(|_| Error::InvalidLength)?;
    let cd_offset = (30usize + file_name.len())
        .checked_add(compressed_data.len())
        .and_then(|n| u32::try_from(n).ok())
        .ok_or(Error::InvalidLength)?;
    if compressed_size == u32::MAX || cd_offset == u32::MAX {
        return Err(Error::InvalidLength);
    }

    let now = 0u32; // Fixed timestamp for reproducibility
    let last_mod_time = (now & 0xFFFF) as u16;
    let last_mod_date = ((now >> 16) & 0xFFFF) as u16;

    // Local file header
    write_u32_le(&mut w, LOCAL_FILE_HEADER_SIG);
    write_u16_le(&mut w, 20); // version needed (2.0)
    write_u16_le(&mut w, 0); // general purpose flag
    write_u16_le(&mut w, compression.to_u16());
    write_u16_le(&mut w, last_mod_time);
    write_u16_le(&mut w, last_mod_date);
    write_u32_le(&mut w, crc32);
    write_u32_le(&mut w, compressed_size);
    write_u32_le(&mut w, uncompressed_size);
    write_u16_le(&mut w, file_name_len);
    write_u16_le(&mut w, 0); // extra field length
    for &b in file_name {
        w.write_bits(b as u32, 8);
    }

    // File data
    for &b in &compressed_data {
        w.write_bits(b as u32, 8);
    }

    let local_header_offset = 0u32;

    // Central directory header
    write_u32_le(&mut w, CENTRAL_DIR_HEADER_SIG);
    write_u16_le(&mut w, 45); // version made by (4.5)
    write_u16_le(&mut w, 20); // version needed
    write_u16_le(&mut w, 0); // general purpose flag
    write_u16_le(&mut w, compression.to_u16());
    write_u16_le(&mut w, last_mod_time);
    write_u16_le(&mut w, last_mod_date);
    write_u32_le(&mut w, crc32);
    write_u32_le(&mut w, compressed_size);
    write_u32_le(&mut w, uncompressed_size);
    write_u16_le(&mut w, file_name_len);
    write_u16_le(&mut w, 0); // extra field length
    write_u16_le(&mut w, 0); // file comment length
    write_u16_le(&mut w, 0); // disk number start
    write_u16_le(&mut w, 0); // internal attributes
    write_u32_le(&mut w, 0); // external attributes
    write_u32_le(&mut w, local_header_offset);
    for &b in file_name {
        w.write_bits(b as u32, 8);
    }

    let cd_size = (w.bit_len() / 8) - cd_offset as usize;

    // End of central directory
    write_u32_le(&mut w, END_CENTRAL_DIR_SIG);
    write_u16_le(&mut w, 0); // disk number
    write_u16_le(&mut w, 0); // disk with CD
    write_u16_le(&mut w, 1); // entries on this disk
    write_u16_le(&mut w, 1); // total entries
    write_u32_le(
        &mut w,
        u32::try_from(cd_size).map_err(|_| Error::InvalidLength)?,
    );
    write_u32_le(&mut w, cd_offset);
    write_u16_le(&mut w, 0); // comment length

    Ok(w.finish())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zip_unzip_roundtrip_deflate() {
        let data = b"hello world hello world hello world";
        let file_name = b"test.txt";
        let zip = zip_single(file_name, data, CompressionMethod::Deflate).unwrap();
        let (decompressed, name) = unzip_single(&zip, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
        assert_eq!(name, file_name);
    }

    #[test]
    fn zip_unzip_roundtrip_stored() {
        let data = b"hello world";
        let file_name = b"test.txt";
        let zip = zip_single(file_name, data, CompressionMethod::Stored).unwrap();
        let (decompressed, name) = unzip_single(&zip, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
        assert_eq!(name, file_name);
    }

    #[test]
    fn zip_unzip_empty() {
        let data = b"";
        let file_name = b"empty.txt";
        let zip = zip_single(file_name, data, CompressionMethod::Deflate).unwrap();
        let (decompressed, name) = unzip_single(&zip, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
        assert_eq!(name, file_name);
    }

    #[test]
    fn zip_unzip_larger() {
        let data = b"The quick brown fox jumps over the lazy dog. ".repeat(100);
        let file_name = b"test.txt";
        let zip = zip_single(file_name, &data, CompressionMethod::Deflate).unwrap();
        let (decompressed, name) = unzip_single(&zip, DEFAULT_LIMIT).unwrap();
        assert_eq!(decompressed, data);
        assert_eq!(name, file_name);
    }
}
