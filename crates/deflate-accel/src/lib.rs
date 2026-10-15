//! Optional accelerated entry points for [`deflate_core`].
//!
//! This crate keeps CPU-specific implementation details in dependencies while
//! leaving `deflate-core` portable, `no_std`, dependency-free, and free of
//! `unsafe` code. Currently, gzip payload checksums use `crc32fast`. On
//! x86-64 CPUs with BMI2, the unchanged core decoder is compiled a second time
//! with those instructions enabled and selected at runtime.
#![deny(unsafe_op_in_unsafe_fn)]

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
        #[cfg(target_arch = "x86_64")]
        if x86::has_bmi2() {
            // SAFETY: `has_bmi2` verified at runtime that this CPU supports
            // every feature enabled on `x86::inflate_into`.
            return unsafe { x86::inflate_into(&mut self.inner, input, out, limit) };
        }
        self.inner.inflate_into(input, out, limit)
    }

    /// Decode gzip members using the accelerated CRC-32/ISO-HDLC backend.
    pub fn gunzip_into(
        &mut self,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<usize, Error> {
        #[cfg(target_arch = "x86_64")]
        if x86::has_bmi2() {
            // SAFETY: as in `inflate_into`, the features were detected.
            return unsafe { x86::gunzip_into(&mut self.inner, input, out, limit) };
        }
        self.inner
            .gunzip_into_with_crc32(input, out, limit, crc32fast::hash)
    }
}

// The same safe core code, compiled with BMI1/BMI2/LZCNT/POPCNT enabled. These
// functions contain no unsafe operations; only calling them requires the
// runtime feature check above.
#[cfg(target_arch = "x86_64")]
mod x86 {
    use super::{Error, InflateResult, Vec};

    pub(super) fn has_bmi2() -> bool {
        std::is_x86_feature_detected!("bmi1")
            && std::is_x86_feature_detected!("bmi2")
            && std::is_x86_feature_detected!("lzcnt")
            && std::is_x86_feature_detected!("popcnt")
    }

    #[target_feature(enable = "bmi1,bmi2,lzcnt,popcnt")]
    pub(super) fn inflate_into(
        inner: &mut deflate_core::Decompressor,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<InflateResult, Error> {
        inner.inflate_into(input, out, limit)
    }

    #[target_feature(enable = "bmi1,bmi2,lzcnt,popcnt")]
    pub(super) fn gunzip_into(
        inner: &mut deflate_core::Decompressor,
        input: &[u8],
        out: &mut Vec<u8>,
        limit: usize,
    ) -> Result<usize, Error> {
        inner.gunzip_into_with_crc32(input, out, limit, crc32fast::hash)
    }
}

/// Decompress gzip into a newly allocated vector, bounded by `limit`.
pub fn gunzip(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut decoder = Decompressor::new();
    let mut output = Vec::new();
    decoder.gunzip_into(input, &mut output, limit)?;
    Ok(output)
}
