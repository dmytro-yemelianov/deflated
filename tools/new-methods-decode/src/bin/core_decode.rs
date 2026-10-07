#[allow(dead_code)]
mod adapter {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../new-methods-bench/src/bin/core_worker.rs"
    ));
    pub fn factory(level: &str, frame: &str) -> Result<Box<dyn Engine>> {
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
    }
}
fn main() {
    new_methods_decode::run("core", adapter::factory);
}
