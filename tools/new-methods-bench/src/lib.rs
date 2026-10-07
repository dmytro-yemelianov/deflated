//! Benchmark tooling only. No added dependencies in either codec crate.
#![forbid(unsafe_code)]

pub mod framing;
pub mod worker;

use deflate_core::bitstream::BitReader;
use deflate_core::block::{
    BlockType, decode_huff_block, read_block_header, read_dynamic_tables, read_stored,
};
use deflate_core::huffman::{fixed_dist, fixed_litlen};

pub type Result<T> = std::result::Result<T, String>;

/// The baseline public decoder permits a suffix. This tooling-only driver
/// performs the same block decoding with exact consumption and known size.
/// No claim of equivalence on malformed inputs, or Rust/model refinement.
pub fn strict_core_inflate(packet: &[u8], expected: usize) -> Result<Vec<u8>> {
    let mut reader = BitReader::new(packet);
    let mut out = Vec::new();
    let drive = (|| {
        loop {
            let header = read_block_header(&mut reader)?;
            match header.btype {
                BlockType::Stored => {
                    let budget = expected.saturating_sub(out.len());
                    read_stored(&mut reader, &mut out, budget)?;
                }
                BlockType::Fixed => decode_huff_block(
                    &fixed_litlen(),
                    &fixed_dist(),
                    &mut reader,
                    &mut out,
                    expected,
                )?,
                BlockType::Dynamic => {
                    let (lit, dist) = read_dynamic_tables(&mut reader)?;
                    decode_huff_block(&lit, &dist, &mut reader, &mut out, expected)?;
                }
            }
            if header.is_final {
                return Ok::<(), deflate_core::Error>(());
            }
        }
    })();
    drive.map_err(|e| format!("DEFLATE: {e:?}"))?;
    if reader.bit_pos().div_ceil(8) != packet.len() || out.len() != expected {
        return Err("DEFLATE consumption or output size".into());
    }
    Ok(out)
}
