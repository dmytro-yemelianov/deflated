//! LZ77 tokens (spec §3.1). Mirrors `spec/Deflate/Tokens.lean`.

use crate::error::Error;
use crate::lz77::copy_back;
use alloc::vec::Vec;

/// One LZ77 step. `dist` is at most 32768, which fits `u16`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Token {
    Literal(u8),
    Match { len: u16, dist: u16 },
}

/// Replay tokens into bytes (Lean `expand`). Matches go through the
/// decoder's own `copy_back`, so there is one definition of copy semantics.
/// For tests and the oracle; fails on a match reaching before the output.
pub fn expand(tokens: &[Token]) -> Result<Vec<u8>, Error> {
    let mut out = Vec::new();
    for t in tokens {
        match *t {
            Token::Literal(b) => out.push(b),
            Token::Match { len, dist } => copy_back(&mut out, usize::from(dist), usize::from(len))?,
        }
    }
    Ok(out)
}
