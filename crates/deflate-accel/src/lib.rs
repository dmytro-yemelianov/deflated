//! Optional accelerated entry points for [`deflate_core`].
//!
//! This crate keeps CPU-specific implementation details in dependencies while
//! leaving `deflate-core` portable, `no_std`, dependency-free, and free of
//! `unsafe` code. Currently, gzip payload checksums use `crc32fast`; raw DEFLATE
//! decoding delegates to the core unchanged.

use alloc::vec::Vec;
extern crate alloc;

pub use deflate_core::{Error, InflateResult};

/// Whole-buffer decoder with reusable core tables and an accelerated gzip CRC.
#[derive(Debug, Default)]
pub struct Decompressor {
    inner: deflate_core::Decompressor,
}

impl Decompressor {
    /// Create a decoder without allocating working buffers.
    pub fn new() -> Self {
        Self::default()
    }

    /// Release retained working buffers.
    pub fn release_buffers(&mut self) {
        self.inner.release_buffers();
    }

    /// Decode one raw DEFLATE stream.
    pub fn inflate_into(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<InflateResult, Error> {
        self.inner.inflate_into(input, out, limit)
    }

    /// Decode gzip members using the accelerated CRC-32/ISO-HDLC backend.
    pub fn gunzip_into(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<usize, Error> {
        self.inner
            .gunzip_into_with_crc32(input, out, limit, crc32fast::hash)
    }
}

/// Decompress gzip into a newly allocated vector, bounded by `limit`.
pub fn gunzip(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut decoder = Decompressor::new();
    let mut output = Vec::new();
    decoder.gunzip_into(input, &mut output, limit)?;
    Ok(output)
}
