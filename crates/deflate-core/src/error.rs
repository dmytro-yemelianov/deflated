//! The error model (spec §10). Every failure in the core is one of these.
//! No input, however malformed, may produce a panic instead of one of these.

/// Deterministic failure modes. Spec §10, §12 (P12).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    /// The stream ended while more bits were required.
    UnexpectedEof,
    /// A block header carried BTYPE = 3.
    InvalidBlockType,
    /// A stored block's NLEN was not the ones' complement of LEN.
    InvalidStoredLength,
    /// A code-length set was over-subscribed, or incomplete where a
    /// complete code is required.
    InvalidHuffmanTree,
    /// A Huffman code was read that the table does not assign a symbol to.
    InvalidCode,
    /// A back-reference distance was 0, or reached before the start of output.
    InvalidDistance,
    /// A length symbol outside 257..=285 appeared where a length was expected.
    InvalidLength,
    /// Decoding would have produced more bytes than the caller allowed.
    OutputLimitExceeded,
}

impl core::fmt::Display for Error {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str(match self {
            Self::UnexpectedEof => "unexpected end of compressed input",
            Self::InvalidBlockType => "invalid block type or container header",
            Self::InvalidStoredLength => "invalid stored length or container size",
            Self::InvalidHuffmanTree => "invalid Huffman tree or container checksum",
            Self::InvalidCode => "invalid Huffman code",
            Self::InvalidDistance => "invalid back-reference distance",
            Self::InvalidLength => "invalid match length",
            Self::OutputLimitExceeded => "decompressed output exceeds the limit",
        })
    }
}

impl core::error::Error for Error {}
