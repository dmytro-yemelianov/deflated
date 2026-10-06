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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tokens::Token;
    use alloc::vec;

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
