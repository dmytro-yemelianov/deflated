use deflate_core::{CompressionLevel, deflate_with_level};
use new_methods_bench::{
    Result, framing, strict_core_inflate,
    worker::{self, Engine},
};

struct Core {
    level: CompressionLevel,
    framing: String,
}
impl Engine for Core {
    fn encode(&self, raw: &[u8]) -> Result<Vec<u8>> {
        framing::wrap(deflate_with_level(raw, self.level), raw, &self.framing)
    }
    fn decode(&self, packet: &[u8], expected: usize) -> Result<Vec<u8>> {
        framing::unwrap(packet, expected, &self.framing, strict_core_inflate)
    }
}
fn main() {
    worker::run(
        "core",
        "{\"codec\":\"deflate-core\",\"version\":\"0.1.0\",\"control\":\"requires b7 core source hash gate\"}",
        |level, frame| {
            framing::check(frame)?;
            let level = match level {
                "fast" => CompressionLevel::Fast,
                "balanced" => CompressionLevel::Balanced,
                "best" => CompressionLevel::Best,
                _ => return Err("invalid preset".into()),
            };
            Ok(Box::new(Core {
                level,
                framing: frame.into(),
            }))
        },
    );
}
