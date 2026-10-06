//! Compressor: the smaller of the dynamic/fixed block stream and stored
//! (spec §3.5). Mirrors `compress` in `spec/Deflate/Compress.lean`.

use crate::deflate::{MAX_STORED, deflate_stored};
use crate::encode_dynamic::{SplitFor, emit_blocks_iter};
use crate::matcher::tokens;
use crate::tokens::Token;
use alloc::vec::Vec;

/// Default split function: uses BLOCK_TOKENS for all blocks.
pub fn default_split_for(_tokens: &[Token]) -> Option<usize> {
    None
}

/// Block stream unless it is not strictly smaller than the stored size
/// (ties go to stored, which decodes faster).
pub fn deflate(input: &[u8]) -> Vec<u8> {
    deflate_with_split(input, default_split_for)
}

/// Block stream with a custom split function. See [`SplitFor`] for the
/// bounded lookahead window and invalid-count fallback. Lean covers only
/// the default splitting policy.
pub fn deflate_with_split(input: &[u8], split_for: SplitFor) -> Vec<u8> {
    let blocks_out = emit_blocks_iter(tokens(input), split_for);
    let blocks = input.len().div_ceil(MAX_STORED).max(1);
    // Exact `deflate_stored` size; saturating only to stay panic-free.
    let stored = input.len().saturating_add(blocks.saturating_mul(5));
    if blocks_out.len() < stored {
        blocks_out
    } else {
        deflate_stored(input)
    }
}
