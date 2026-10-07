use miniz_oxide::inflate::{
    TINFLStatus,
    core::{
        DecompressorOxide, decompress, inflate_flags::TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF,
    },
};
use new_methods_bench::{
    Result, framing,
    worker::{self, Engine},
};

struct Miniz {
    level: u8,
    framing: String,
}
fn strict_miniz(packet: &[u8], expected: usize) -> Result<Vec<u8>> {
    // Match decompress_to_vec_with_limit's fresh state and geometric output
    // growth, additionally checking its final consumed count and exact size.
    let mut out = vec![0; packet.len().saturating_mul(2).min(expected)];
    let mut state = Box::<DecompressorOxide>::default();
    let (mut consumed, mut written) = (0, 0);
    loop {
        let (status, input_n, output_n) = decompress(
            &mut state,
            &packet[consumed..],
            &mut out,
            written,
            TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF,
        );
        consumed += input_n;
        written += output_n;
        if status == TINFLStatus::Done {
            if consumed != packet.len() || written != expected {
                return Err("miniz consumption or size".into());
            }
            out.truncate(written);
            return Ok(out);
        }
        if status != TINFLStatus::HasMoreOutput || out.len() >= expected {
            return Err(format!("miniz {status:?}"));
        }
        out.resize(out.len().saturating_mul(2).max(1).min(expected), 0);
    }
}
impl Engine for Miniz {
    fn encode(&self, raw: &[u8]) -> Result<Vec<u8>> {
        framing::wrap(
            miniz_oxide::deflate::compress_to_vec(raw, self.level),
            raw,
            &self.framing,
        )
    }
    fn decode(&self, packet: &[u8], expected: usize) -> Result<Vec<u8>> {
        framing::unwrap(packet, expected, &self.framing, strict_miniz)
    }
}
fn main() {
    worker::run(
        "miniz",
        "{\"codec\":\"miniz_oxide\",\"version\":\"0.8.9\"}",
        |level, frame| {
            framing::check(frame)?;
            let level = level.parse::<u8>().map_err(|_| "invalid level")?;
            if ![1, 6, 9].contains(&level) {
                return Err("level outside roster".into());
            }
            Ok(Box::new(Miniz {
                level,
                framing: frame.into(),
            }))
        },
    );
}
