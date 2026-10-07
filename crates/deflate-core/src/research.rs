//! Experimental tuning adapter, available only with `research-tuning`.
//! Configurations are bounded heuristics; emitted matches and Huffman choices
//! use the normal checks. This API and measured settings are not presets.

use alloc::vec::Vec;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Index {
    Dual,
    Trigram,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConfigError {
    Probes,
    InsertionTail,
    BlockTokens,
}

impl core::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str(match self {
            Self::Probes => "probes must be in 1..=1024",
            Self::InsertionTail => "insertion tail must be in 0..=32; zero indexes all positions",
            Self::BlockTokens => "block tokens must be 256, 1024, 4096 or 16384",
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config {
    probes: usize,
    lazy: bool,
    insert_tail: usize,
    index: Index,
    block_tokens: usize,
}

impl Config {
    pub fn new(
        probes: usize,
        lazy: bool,
        insert_tail: usize,
        index: Index,
        block_tokens: usize,
    ) -> Result<Self, ConfigError> {
        if !(1..=1024).contains(&probes) {
            return Err(ConfigError::Probes);
        }
        if insert_tail > 32 {
            return Err(ConfigError::InsertionTail);
        }
        if !matches!(block_tokens, 256 | 1024 | 4096 | 16384) {
            return Err(ConfigError::BlockTokens);
        }
        Ok(Self {
            probes,
            lazy,
            insert_tail,
            index,
            block_tokens,
        })
    }

    pub fn probes(self) -> usize {
        self.probes
    }
    pub fn lazy(self) -> bool {
        self.lazy
    }
    pub fn insert_tail(self) -> usize {
        self.insert_tail
    }
    pub fn index(self) -> Index {
        self.index
    }
    pub fn block_tokens(self) -> usize {
        self.block_tokens
    }

    /// Table capacities only: excludes output, emitter buffers and process RSS.
    pub fn matcher_table_bytes(self) -> usize {
        let one_index =
            (1 << 15) * core::mem::size_of::<u32>() + 32768 * core::mem::size_of::<u16>();
        one_index * if self.index == Index::Dual { 2 } else { 1 }
    }
}

pub fn deflate(input: &[u8], config: Config) -> Vec<u8> {
    crate::compress::configured(input, config)
}

/// Bounded regional effort. After `light` visits, a match of at least
/// `stop_length` bytes ends the search; ambiguous positions retain the full
/// base probe budget. Lazy lookahead is restricted to matches <= its limit.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AdaptiveConfig {
    base: Config,
    light: usize,
    stop_length: usize,
    lazy_limit: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AdaptiveError {
    LightProbes,
    StopLength,
    LazyLimit,
}

impl AdaptiveConfig {
    pub fn new(
        base: Config,
        light: usize,
        stop_length: usize,
        lazy_limit: usize,
    ) -> Result<Self, AdaptiveError> {
        if light == 0 || light > base.probes() {
            return Err(AdaptiveError::LightProbes);
        }
        if !(3..=258).contains(&stop_length) {
            return Err(AdaptiveError::StopLength);
        }
        if lazy_limit > 258 {
            return Err(AdaptiveError::LazyLimit);
        }
        Ok(Self {
            base,
            light,
            stop_length,
            lazy_limit,
        })
    }
    pub fn base(self) -> Config {
        self.base
    }
    pub fn light(self) -> usize {
        self.light
    }
    pub fn stop_length(self) -> usize {
        self.stop_length
    }
    pub fn lazy_limit(self) -> usize {
        self.lazy_limit
    }
}

pub fn deflate_adaptive(input: &[u8], config: AdaptiveConfig) -> Vec<u8> {
    crate::compress::adaptive(input, config)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tokens::Token;
    use alloc::vec;

    #[test]
    fn adaptive_bounds_and_full_effort_equivalence() {
        let base = Config::new(128, true, 0, Index::Trigram, 16384).unwrap();
        assert_eq!(
            AdaptiveConfig::new(base, 0, 8, 16),
            Err(AdaptiveError::LightProbes)
        );
        assert_eq!(
            AdaptiveConfig::new(base, 129, 8, 16),
            Err(AdaptiveError::LightProbes)
        );
        assert_eq!(
            AdaptiveConfig::new(base, 4, 2, 16),
            Err(AdaptiveError::StopLength)
        );
        assert_eq!(
            AdaptiveConfig::new(base, 4, 259, 16),
            Err(AdaptiveError::StopLength)
        );
        assert_eq!(
            AdaptiveConfig::new(base, 4, 8, 259),
            Err(AdaptiveError::LazyLimit)
        );
        let mut word = 43_u32;
        let input: Vec<u8> = (0..3 * 32768 + 259)
            .map(|i| {
                word = word.wrapping_mul(1664525).wrapping_add(1013904223);
                if i % 8192 < 4096 {
                    (word >> 24) as u8
                } else {
                    b"abcabd"[i % 6]
                }
            })
            .collect();
        for index in [Index::Dual, Index::Trigram] {
            let base = Config::new(128, true, 0, index, 16384).unwrap();
            let full = AdaptiveConfig::new(base, 128, 258, 258).unwrap();
            assert_eq!(deflate_adaptive(&input, full), deflate(&input, base));
            for light in [4, 16] {
                for stop in [4, 8, 16] {
                    let config = AdaptiveConfig::new(base, light, stop, 16).unwrap();
                    let tokens: Vec<_> =
                        crate::matcher::tokens_with_adaptive(&input, config).collect();
                    assert_eq!(crate::tokens::expand(&tokens).unwrap(), input);
                    let mut pos = 0;
                    for token in tokens {
                        match token {
                            Token::Literal(byte) => {
                                assert_eq!(input[pos], byte);
                                pos += 1;
                            }
                            Token::Match { len, dist } => {
                                assert!(crate::matcher::accept(
                                    &input,
                                    pos,
                                    len as usize,
                                    dist as usize
                                ));
                                pos += len as usize;
                            }
                        }
                    }
                    let packet = deflate_adaptive(&input, config);
                    assert_eq!(crate::inflate(&packet).unwrap(), input);
                    assert_eq!(
                        miniz_oxide::inflate::decompress_to_vec(&packet).unwrap(),
                        input
                    );
                }
            }
        }
    }

    #[test]
    fn rejects_unbounded_and_unsupported_settings() {
        for probes in [0, 1025, usize::MAX] {
            assert_eq!(
                Config::new(probes, true, 0, Index::Dual, 16384),
                Err(ConfigError::Probes)
            );
        }
        assert_eq!(
            Config::new(1, false, 33, Index::Trigram, 256),
            Err(ConfigError::InsertionTail)
        );
        for block in [0, 255, 257, 16385, usize::MAX] {
            assert_eq!(
                Config::new(1, false, 0, Index::Trigram, block),
                Err(ConfigError::BlockTokens)
            );
        }
    }

    #[test]
    fn configurations_cover_input_with_accepted_tokens_and_roundtrip() {
        let mut seed = 1951_u32;
        let mixed: Vec<_> = (0..2 * 32768 + 259)
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
        for input in [
            mixed,
            vec![7; 32769],
            (0..32769).map(|i| b"abcabcabd"[i % 9]).collect(),
        ] {
            for probes in [1, 1024] {
                for lazy in [false, true] {
                    for tail in [0, 1, 32] {
                        for index in [Index::Dual, Index::Trigram] {
                            let config = Config::new(probes, lazy, tail, index, 1024).unwrap();
                            let mut pos = 0;
                            for token in crate::matcher::tokens_with_config(&input, config) {
                                match token {
                                    Token::Literal(byte) => {
                                        assert_eq!(input[pos], byte);
                                        pos += 1;
                                    }
                                    Token::Match { len, dist } => {
                                        assert!(crate::matcher::accept(
                                            &input,
                                            pos,
                                            len as usize,
                                            dist as usize
                                        ));
                                        pos += len as usize;
                                    }
                                }
                            }
                            assert_eq!(pos, input.len());
                            let packed = deflate(&input, config);
                            assert_eq!(crate::inflate(&packed).unwrap(), input);
                            assert_eq!(
                                miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
                                input
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn all_split_sizes_handle_empty_and_word_window_stored_boundaries() {
        for block in [256, 1024, 4096, 16384] {
            let config = Config::new(16, true, 0, Index::Dual, block).unwrap();
            for size in [
                0, 1, 2, 3, 4, 257, 258, 259, 32767, 32768, 32769, 65535, 65536, 65537,
            ] {
                let input: Vec<_> = (0..size).map(|i| (i * 13) as u8).collect();
                let packed = deflate(&input, config);
                assert_eq!(
                    miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
                    input
                );
                assert!(packed.len() <= input.len() + input.len().div_ceil(65535).max(1) * 5);
            }
        }
    }
}
