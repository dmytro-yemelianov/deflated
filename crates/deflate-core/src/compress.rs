//! Compressor: the smaller of the dynamic/fixed block stream and stored
//! (spec §3.5). Mirrors `compress` in `spec/Deflate/Compress.lean`.

use crate::deflate::{MAX_STORED, deflate_stored};
use crate::encode_dynamic::{Freqs, SplitFor, emit_blocks_iter, lengths_for_freqs};
use crate::matcher::{CompressionLevel, tokens_with_level, use_flat_matcher};
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

/// Compress with a speed/size search preset. Every preset uses the same
/// checked matcher and Huffman emitter, and the exact stored-size fallback.
pub fn deflate_with_level(input: &[u8], level: CompressionLevel) -> Vec<u8> {
    let split_for = if level == CompressionLevel::Best {
        size_split_for
    } else {
        default_split_for
    };
    choose_stored(input, matched_blocks(input, level, split_for))
}

fn block_bits(tokens: &[Token]) -> usize {
    let frequencies = Freqs::from_tokens(tokens);
    let fixed = frequencies.fixed_bits();
    lengths_for_freqs(&frequencies).map_or(fixed, |(lit, dist, cl)| {
        fixed.min(frequencies.dynamic_bits(&lit, &dist, &cl))
    })
}

// Compare actual header and payload bit costs, including one end symbol per
// block. Only Best pays for this extra analysis. The checked split interface
// keeps every result within the model's 16384-token lookahead bound.
fn size_split_for(tokens: &[Token]) -> Option<usize> {
    if tokens.len() < 1024 {
        return None;
    }
    let mut best = block_bits(tokens);
    let mut split = None;
    for numerator in 1..=3 {
        let at = tokens.len() * numerator / 4;
        let bits = block_bits(&tokens[..at]).saturating_add(block_bits(&tokens[at..]));
        if bits.saturating_add(16) < best {
            best = bits;
            split = Some(at);
        }
    }
    split
}

/// Block stream with a custom split function. See [`SplitFor`] for the
/// bounded lookahead window and invalid-count fallback. Lean's
/// `decode_compressSplit` covers every checked splitting policy.
pub fn deflate_with_split(input: &[u8], split_for: SplitFor) -> Vec<u8> {
    let blocks_out = matched_blocks(input, CompressionLevel::Balanced, split_for);
    choose_stored(input, blocks_out)
}

fn matched_blocks(input: &[u8], level: CompressionLevel, split_for: SplitFor) -> Vec<u8> {
    if level == CompressionLevel::Balanced && use_flat_matcher(input) {
        emit_blocks_iter(crate::matcher_flat::tokens(input), split_for)
    } else {
        emit_blocks_iter(tokens_with_level(input, level), split_for)
    }
}

fn choose_stored(input: &[u8], blocks_out: Vec<u8>) -> Vec<u8> {
    let blocks = input.len().div_ceil(MAX_STORED).max(1);
    // Exact `deflate_stored` size; saturating only to stay panic-free.
    let stored = input.len().saturating_add(blocks.saturating_mul(5));
    if blocks_out.len() < stored {
        blocks_out
    } else {
        deflate_stored(input)
    }
}

#[cfg(feature = "research-tuning")]
pub(crate) fn configured(input: &[u8], config: crate::research::Config) -> Vec<u8> {
    fn split<const N: usize>(_: &[Token]) -> Option<usize> {
        Some(N)
    }
    let split_for: SplitFor = match config.block_tokens() {
        256 => split::<256>,
        1024 => split::<1024>,
        4096 => split::<4096>,
        16384 => split::<16384>,
        _ => unreachable!("validated research configuration"),
    };
    choose_stored(
        input,
        emit_blocks_iter(crate::matcher::tokens_with_config(input, config), split_for),
    )
}

#[cfg(feature = "research-tuning")]
pub(crate) fn adaptive(input: &[u8], config: crate::research::AdaptiveConfig) -> Vec<u8> {
    fn split<const N: usize>(_: &[Token]) -> Option<usize> {
        Some(N)
    }
    let split_for: SplitFor = match config.base().block_tokens() {
        256 => split::<256>,
        1024 => split::<1024>,
        4096 => split::<4096>,
        16384 => split::<16384>,
        _ => unreachable!("validated research configuration"),
    };
    choose_stored(
        input,
        emit_blocks_iter(
            crate::matcher::tokens_with_adaptive(input, config),
            split_for,
        ),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::vec;

    #[test]
    fn size_split_detects_distribution_changes_and_counts_header_cost() {
        let uniform = vec![Token::Literal(b'a'); 4096];
        assert_eq!(size_split_for(&uniform), None);
        let mut changed = vec![Token::Literal(b'a'); 2048];
        changed.extend(vec![Token::Literal(b'b'); 2048]);
        let split = size_split_for(&changed).expect("distinct distributions benefit from a split");
        assert_eq!(split, 2048);
        assert!(
            block_bits(&changed[..split]) + block_bits(&changed[split..]) + 16
                < block_bits(&changed)
        );
        assert_eq!(size_split_for(&changed[..100]), None);
    }

    #[test]
    fn all_presets_roundtrip_boundaries_with_independent_decoder() {
        for size in [
            0, 1, 2, 3, 4, 257, 258, 259, 32767, 32768, 32769, 65535, 65536, 65537,
        ] {
            let mut seed = 0x1951u32;
            let input: Vec<_> = (0..size)
                .map(|i| {
                    seed ^= seed << 13;
                    seed ^= seed >> 17;
                    seed ^= seed << 5;
                    if i % 4096 < 2048 {
                        (seed % 4) as u8
                    } else {
                        seed as u8
                    }
                })
                .collect();
            for level in [
                CompressionLevel::Fast,
                CompressionLevel::Balanced,
                CompressionLevel::Best,
            ] {
                let stream = deflate_with_level(&input, level);
                assert_eq!(crate::inflate(&stream).unwrap(), input);
                assert_eq!(
                    miniz_oxide::inflate::decompress_to_vec(&stream).unwrap(),
                    input
                );
                assert!(stream.len() <= input.len() + input.len().div_ceil(MAX_STORED).max(1) * 5);
            }
        }
    }
}
