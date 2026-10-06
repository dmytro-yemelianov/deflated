//! RFC 1951 DEFLATE core.
//!
//! This crate is the proof-critical part of the project. It is `no_std`,
//! has no runtime dependencies, and contains no `unsafe_code`. The Lean model in
//! `spec/Deflate/` mirrors it module for module.
//!
//! Nothing here is "formally verified". The Lean theorems are about the Lean
//! model; this code is connected to that model by differential testing only.
//! See `docs/verification-boundary.md`.
#![no_std]
#![forbid(unsafe_code)]

extern crate alloc;

pub mod bitstream;
pub mod bitwriter;
pub mod block;
pub mod compress;
pub mod crc32;
pub mod deflate;
pub mod encode_dynamic;
pub mod encode_fixed;
pub mod error;
pub mod gzip;
pub mod huffman;
pub mod huffman_build;
pub mod inflate;
pub mod lz77;
pub mod matcher;
mod matcher_flat;
pub mod tokens;
pub mod zip;

pub use compress::{default_split_for, deflate, deflate_with_level};
pub use deflate::{MAX_STORED, deflate_stored};
pub use error::Error;
pub use inflate::{DEFAULT_LIMIT, inflate, inflate_with_limit};
pub use matcher::CompressionLevel;
