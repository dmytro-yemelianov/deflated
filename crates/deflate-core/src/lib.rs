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
pub mod block;
pub mod error;
pub mod huffman;
pub mod inflate;
pub mod lz77;

pub use error::Error;
pub use inflate::{inflate, inflate_with_limit};
