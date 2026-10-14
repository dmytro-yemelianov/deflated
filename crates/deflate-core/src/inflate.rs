//! The decoder driver (RFC 1951 §3.2.3): read blocks until BFINAL.
//! Mirrors `spec/Deflate/Decode.lean`.

use crate::bitstream::BitReader;
use crate::block::{BlockType, decode_huff_block, decode_tokens, read_block_header, read_stored};
use crate::decode_table::fixed_tables;
use crate::error::Error;
use alloc::vec::Vec;

/// The limit [`inflate`] uses: 1 GiB. Chosen so that the convenience entry
/// point cannot be turned into an out-of-memory condition by a stream a few
/// hundred bytes long, while staying far above any realistic document.
/// Callers handling untrusted input should pass their own, smaller, limit
/// to [`inflate_with_limit`] (spec §11).
pub const DEFAULT_LIMIT: usize = 1 << 30;

/// Decode, with [`DEFAULT_LIMIT`] as the ceiling.
pub fn inflate(input: &[u8]) -> Result<Vec<u8>, Error> {
    inflate_with_limit(input, DEFAULT_LIMIT)
}

/// Decode, refusing to produce more than `limit` bytes.
///
/// The limit is checked before every append and before every back-copy, so a
/// stream that would expand past it is refused without allocating past it.
/// `Ok(v)` implies `v.len() <= limit`.
pub fn inflate_with_limit(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut out: Vec<u8> = Vec::new();
    inflate_into(input, &mut out, limit)?;
    Ok(out)
}

/// Successful decoding of one raw DEFLATE stream.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InflateResult {
    /// Bytes containing the stream, including padding in the final byte.
    /// Bytes after that byte are not consumed or validated.
    pub bytes_consumed: usize,
    /// Decoded bytes in the output buffer.
    pub bytes_written: usize,
}

/// Decode one raw stream into a reusable output buffer.
///
/// Clears `out` before decoding; existing bytes are never a dictionary. Its
/// allocation is reused and may grow. `limit` bounds decoded length, not the
/// capacity of a previously allocated buffer. On error `out` is empty and its
/// allocation is retained. This is a whole-buffer API, not streaming.
///
/// The returned consumption includes the final partially used byte. To reject
/// a suffix, require `result.bytes_consumed == input.len()`; the convenience
/// functions accept a suffix for compatibility.
///
/// ```
/// use deflate_core::{deflate, inflate_into};
/// let packet = deflate(b"hello");
/// let mut output = Vec::with_capacity(1024);
/// let result = inflate_into(&packet, &mut output, 1024)?;
/// assert_eq!(result.bytes_consumed, packet.len());
/// assert_eq!(output, b"hello");
/// # Ok::<(), deflate_core::Error>(())
/// ```
pub fn inflate_into(input: &[u8], out: &mut Vec<u8>, limit: usize) -> Result<InflateResult, Error> {
    out.clear();
    let mut r = BitReader::new(input);
    if let Err(error) = decode_into(&mut r, out, limit) {
        out.clear();
        return Err(error);
    }
    Ok(InflateResult {
        bytes_consumed: r.bit_pos().div_ceil(8),
        bytes_written: out.len(),
    })
}

// The caller supplies an empty buffer: backreferences cannot cross streams.
pub(crate) fn decode_into(
    r: &mut BitReader<'_>,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    decode_reusing(&mut crate::block::DynamicTables::default(), r, out, limit)
}

#[inline]
fn decode_blocks(
    r: &mut BitReader<'_>,
    out: &mut Vec<u8>,
    limit: usize,
    mut dynamic: impl FnMut(&mut BitReader<'_>, &mut Vec<u8>, usize) -> Result<(), Error>,
) -> Result<(), Error> {
    loop {
        let header = read_block_header(r)?;
        match header.btype {
            BlockType::Stored => {
                let budget = limit.saturating_sub(out.len());
                read_stored(r, out, budget)?;
            }
            BlockType::Fixed => {
                if r.byte_window().len() < 64 {
                    // Avoid batch/table-action setup for tiny fixed blocks.
                    // This is the existing compact symbol decoder, with the
                    // same cursor, suffix and error behavior as the bulk path.
                    let lit = crate::huffman::fixed_litlen();
                    let dst = crate::huffman::fixed_dist();
                    decode_huff_block(&lit, &dst, r, out, limit)?;
                } else {
                    let (lit, dst) = fixed_tables();
                    decode_tokens(&lit, &dst, r, out, limit)?;
                }
            }
            BlockType::Dynamic => {
                dynamic(r, out, limit)?;
            }
        }
        if header.is_final {
            return Ok(());
        }
    }
}

fn decode_reusing(
    tables: &mut crate::block::DynamicTables,
    r: &mut BitReader<'_>,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    decode_blocks(r, out, limit, |r, out, limit| {
        let (lit, dist) = tables.read(r)?;
        decode_tokens(lit, dist, r, out, limit)
    })
}

/// Whole-buffer DEFLATE/gzip decoder with reusable working allocations.
///
/// Tables are allocated lazily for dynamic blocks (about 20 KiB retained after
/// use). Gzip may also retain a member scratch buffer. Input, output history and
/// dictionaries are never retained between calls; every call starts a new stream,
/// including after an error. This is not a streaming decoder.
///
/// Output buffers and limits have the same contracts as [`inflate_into`] and
/// [`crate::gunzip_into`]. Limits bound decoded length, not retained capacity.
/// Use [`Self::release_buffers`] or drop the decoder to free working memory.
///
/// ```
/// use deflate_core::{Decompressor, deflate};
/// let mut decoder = Decompressor::new();
/// let mut output = Vec::new();
/// for data in [b"first".as_slice(), b"second".as_slice()] {
///     decoder.inflate_into(&deflate(data), &mut output, 1024)?;
///     assert_eq!(output, data);
/// }
/// # Ok::<(), deflate_core::Error>(())
/// ```
#[derive(Debug, Default)]
pub struct Decompressor {
    tables: crate::block::DynamicTables,
    member: Vec<u8>,
}

impl Decompressor {
    /// Create a decoder without allocating working buffers.
    pub fn new() -> Self {
        Self::default()
    }

    /// Release retained working buffers. The caller's output is unaffected.
    pub fn release_buffers(&mut self) {
        *self = Self::new();
    }

    /// Decode one raw stream, replacing output and returning its consumption.
    /// See [`inflate_into`] for suffix, limit and error behavior.
    pub fn inflate_into(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<InflateResult, Error> {
        out.clear();
        let mut reader = BitReader::new(input);
        if let Err(error) = decode_reusing(&mut self.tables, &mut reader, out, limit) {
            out.clear();
            return Err(error);
        }
        Ok(InflateResult {
            bytes_consumed: reader.bit_pos().div_ceil(8),
            bytes_written: out.len(),
        })
    }

    /// Decode all gzip members, replacing output and checking every checksum.
    /// See [`crate::gunzip_into`] for padding, limit and error behavior.
    pub fn gunzip_into(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<usize, Error> {
        self.gunzip_into_with_crc32(input, out, limit, crate::crc32::Crc32::compute)
    }

    /// Decode gzip using a caller-supplied CRC-32/ISO-HDLC implementation.
    ///
    /// `crc32` must return the standard finalized gzip CRC-32 for every input.
    /// The default [`Self::gunzip_into`] keeps the portable implementation in
    /// this crate. This hook lets a separate platform crate provide hardware
    /// acceleration without adding dependencies or `unsafe` to the core.
    pub fn gunzip_into_with_crc32(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
        crc32: impl FnMut(&[u8]) -> u32,
    ) -> Result<usize, Error> {
        crate::gzip::gunzip_reusing_with_crc32(
            input,
            out,
            &mut self.member,
            limit,
            |r, out, limit| decode_reusing(&mut self.tables, r, out, limit),
            crc32,
        )
    }
}
