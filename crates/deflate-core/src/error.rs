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
