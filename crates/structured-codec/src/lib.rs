//! Experimental DSC1, as specified in docs/structured-codec-spec.md.
//! No claim of formal verification or superiority over existing codecs.
#![no_std]
#![forbid(unsafe_code)]

extern crate alloc;

mod decode;
mod encode;
mod wire;

pub use decode::{DEFAULT_LIMIT, decode, decode_with_limit};
pub use encode::{DictionaryMode, Settings, encode, encode_untransformed};
pub use wire::Error;
