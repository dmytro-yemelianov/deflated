//! Length/distance codes (RFC 1951 §3.2.5) and the back copy (§3.2.3).
//! Mirrors `spec/Deflate/LZ77.lean`.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

/// Length codes 257..=285.
pub const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
    163, 195, 227, 258,
];
pub const LENGTH_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];

/// Distance codes 0..=29.
pub const DIST_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
pub const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];

/// Resolve a length symbol. 286 and 287 exist in the fixed code but RFC 1951
/// §3.2.6 says they may never appear in a stream.
pub fn read_length(sym: u16, r: &mut BitReader) -> Result<usize, Error> {
    if !(257..=285).contains(&sym) {
        return Err(Error::InvalidLength);
    }
    let i = (sym - 257) as usize;
    let (base, extra) = match (LENGTH_BASE.get(i), LENGTH_EXTRA.get(i)) {
        (Some(b), Some(e)) => (*b, *e),
        _ => return Err(Error::InvalidLength),
    };
    Ok(base as usize + r.read_bits(extra as u32)? as usize)
}

/// Resolve a distance symbol. 30 and 31 exist in the fixed code but may never
/// appear.
pub fn read_distance(sym: u16, r: &mut BitReader) -> Result<usize, Error> {
    let i = sym as usize;
    let (base, extra) = match (DIST_BASE.get(i), DIST_EXTRA.get(i)) {
        (Some(b), Some(e)) => (*b, *e),
        _ => return Err(Error::InvalidDistance),
    };
    Ok(base as usize + r.read_bits(extra as u32)? as usize)
}

/// Below this length `copy_back` goes byte by byte (picked by `make perf`).
const SHORT_COPY: usize = 16;

/// Copy `len` bytes from `dist` back so that `len > dist` repeats what this
/// very copy produces (RFC 1951 §3.2.3). On error nothing is appended.
///
/// Lean's `copyGo` goes one byte at a time; past `SHORT_COPY` this copies in
/// chunks that only read bytes already written. Each chunk takes the whole
/// window from `start` to the end, so the window doubles and stays a multiple
/// of `dist`, which puts every chunk in phase with the byte-wise copy. The
/// differential and `lz77_tests` reference checks hold the two together.
pub fn copy_back(out: &mut Vec<u8>, dist: usize, len: usize) -> Result<(), Error> {
    let start = match out.len().checked_sub(dist) {
        Some(s) if dist != 0 => s,
        _ => return Err(Error::InvalidDistance),
    };
    out.reserve(len);
    if len < SHORT_COPY {
        // Short matches dominate text; here a bulk copy's per-call cost
        // outweighs what it saves, so this is `copyGo` as written.
        for _ in 0..len {
            let b = match out.len().checked_sub(dist).and_then(|i| out.get(i)) {
                Some(b) => *b,
                None => return Err(Error::InvalidDistance),
            };
            out.push(b);
        }
        return Ok(());
    }
    let mut remaining = len;
    while remaining > 0 {
        // `out.len() - start >= dist >= 1`, so each pass makes progress and
        // `end <= out.len()`. The checks keep that enforced rather than
        // argued, so `extend_from_within` cannot panic.
        let avail = out.len().saturating_sub(start);
        let n = remaining.min(avail);
        let end = match start.checked_add(n) {
            Some(e) if n != 0 && e <= out.len() => e,
            _ => return Err(Error::InvalidDistance),
        };
        out.extend_from_within(start..end);
        remaining -= n;
    }
    Ok(())
}
