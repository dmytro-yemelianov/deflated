//! CRC32 (RFC 1952 §8, polynomial 0xEDB88320).
//!
//! `spec/Deflate/CRC32.lean` computes the same reflected checksum bit by bit.
//! Rust correspondence is tested, not proved; no collision-freedom claim is made.
//!
//! Portable slicing-by-sixteen implementation. Tables are computed at compile
//! time. The byte-at-a-time tail also handles short incremental updates.

/// CRC32 polynomial (reflected): 0xEDB88320.
const POLY: u32 = 0xEDB88320;

/// Precomputed CRC32 table (256 entries).
const CRC32_TABLE: [u32; 256] = make_crc32_table();

const CRC32_SLICES: [[u32; 256]; 16] = make_crc32_slices();

const fn make_crc32_slices() -> [[u32; 256]; 16] {
    let mut tables = [[0; 256]; 16];
    tables[0] = CRC32_TABLE;
    let mut slice = 1;
    while slice < 16 {
        let mut byte = 0;
        while byte < 256 {
            let crc = tables[slice - 1][byte];
            tables[slice][byte] = CRC32_TABLE[(crc & 255) as usize] ^ (crc >> 8);
            byte += 1;
        }
        slice += 1;
    }
    tables
}

/// Compute the CRC32 table at compile time.
const fn make_crc32_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut c = i as u32;
        let mut j = 0;
        while j < 8 {
            if c & 1 != 0 {
                c = POLY ^ (c >> 1);
            } else {
                c >>= 1;
            }
            j += 1;
        }
        table[i] = c;
        i += 1;
    }
    table
}

// Keep the large checksum loop out of framing callers: its registers and
// table setup need not burden empty/tiny gzip members or short updates.
#[inline(never)]
fn update_slices(mut crc: u32, data: &[u8]) -> u32 {
    let mut chunks = data.chunks_exact(16);
    for bytes in &mut chunks {
        let low = u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) ^ crc;
        crc = CRC32_SLICES[15][(low & 255) as usize]
            ^ CRC32_SLICES[14][((low >> 8) & 255) as usize]
            ^ CRC32_SLICES[13][((low >> 16) & 255) as usize]
            ^ CRC32_SLICES[12][(low >> 24) as usize]
            ^ CRC32_SLICES[11][bytes[4] as usize]
            ^ CRC32_SLICES[10][bytes[5] as usize]
            ^ CRC32_SLICES[9][bytes[6] as usize]
            ^ CRC32_SLICES[8][bytes[7] as usize]
            ^ CRC32_SLICES[7][bytes[8] as usize]
            ^ CRC32_SLICES[6][bytes[9] as usize]
            ^ CRC32_SLICES[5][bytes[10] as usize]
            ^ CRC32_SLICES[4][bytes[11] as usize]
            ^ CRC32_SLICES[3][bytes[12] as usize]
            ^ CRC32_SLICES[2][bytes[13] as usize]
            ^ CRC32_SLICES[1][bytes[14] as usize]
            ^ CRC32_SLICES[0][bytes[15] as usize];
    }
    update_tail(crc, chunks.remainder())
}

#[inline]
fn update_tail(mut crc: u32, data: &[u8]) -> u32 {
    // Keep eight-byte updates efficient too (including short gzip data).
    let mut tail = data;
    if let Some(bytes) = tail.first_chunk::<8>() {
        let low = u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) ^ crc;
        crc = CRC32_SLICES[7][(low & 255) as usize]
            ^ CRC32_SLICES[6][((low >> 8) & 255) as usize]
            ^ CRC32_SLICES[5][((low >> 16) & 255) as usize]
            ^ CRC32_SLICES[4][(low >> 24) as usize]
            ^ CRC32_SLICES[3][bytes[4] as usize]
            ^ CRC32_SLICES[2][bytes[5] as usize]
            ^ CRC32_SLICES[1][bytes[6] as usize]
            ^ CRC32_SLICES[0][bytes[7] as usize];
        tail = &tail[8..];
    }
    for &byte in tail {
        let idx = (crc ^ byte as u32) & 0xFF;
        crc = CRC32_TABLE[idx as usize] ^ (crc >> 8);
    }
    crc
}

/// CRC32 state for incremental computation.
#[derive(Clone, Copy)]
pub struct Crc32 {
    value: u32,
}

impl Crc32 {
    /// Create a new CRC32 calculator (initial value 0xFFFFFFFF per RFC 1952).
    pub fn new() -> Self {
        Crc32 { value: 0xFFFFFFFF }
    }

    /// Update with new data.
    #[inline]
    pub fn update(&mut self, data: &[u8]) {
        self.value = if data.len() < 16 {
            update_tail(self.value, data)
        } else {
            update_slices(self.value, data)
        };
    }

    /// Finalize and return the CRC32 value.
    pub fn finalize(self) -> u32 {
        self.value ^ 0xFFFFFFFF
    }

    /// Compute CRC32 of data in one call.
    pub fn compute(data: &[u8]) -> u32 {
        let mut c = Crc32::new();
        c.update(data);
        c.finalize()
    }
}

impl Default for Crc32 {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc32_empty_is_zero() {
        // Standard CRC32: initial 0xFFFFFFFF, process bytes, final XOR 0xFFFFFFFF
        // Empty: 0xFFFFFFFF ^ 0xFFFFFFFF = 0
        assert_eq!(Crc32::compute(&[]), 0);
    }

    #[test]
    fn crc32_known_values() {
        // Standard test vectors
        assert_eq!(Crc32::compute(b""), 0x00000000);
        assert_eq!(Crc32::compute(b"a"), 0xE8B7BE43);
        assert_eq!(Crc32::compute(b"abc"), 0x352441C2);
        assert_eq!(Crc32::compute(b"123456789"), 0xCBF43926);
    }

    #[test]
    fn crc32_incremental() {
        let mut c = Crc32::new();
        c.update(b"123");
        c.update(b"456");
        c.update(b"789");
        assert_eq!(c.finalize(), 0xCBF43926);
    }
}
