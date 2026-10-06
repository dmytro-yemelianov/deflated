//! CRC32 (RFC 1952 §8, polynomial 0xEDB88320).
//!
//! This is outside the Lean verification boundary (spec §6). The Lean model
//! in `spec/Deflate/` does not cover gzip framing.
//!
//! Table-driven implementation for speed. The table is computed once at
//! startup via `const` evaluation.

/// CRC32 polynomial (reflected): 0xEDB88320.
const POLY: u32 = 0xEDB88320;

/// Precomputed CRC32 table (256 entries).
const CRC32_TABLE: [u32; 256] = make_crc32_table();

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
    pub fn update(&mut self, data: &[u8]) {
        let mut crc = self.value;
        for &byte in data {
            let idx = (crc ^ byte as u32) & 0xFF;
            crc = CRC32_TABLE[idx as usize] ^ (crc >> 8);
        }
        self.value = crc;
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
