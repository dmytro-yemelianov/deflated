#[allow(dead_code)]
mod adapter {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../new-methods-bench/src/bin/miniz_worker.rs"
    ));
    pub fn factory(level: &str, frame: &str) -> Result<Box<dyn Engine>> {
        framing::check(frame)?;
        let level = level.parse::<u8>().map_err(|_| "invalid level")?;
        if ![1, 6, 9].contains(&level) {
            return Err("level outside roster".into());
        }
        Ok(Box::new(Miniz {
            level,
            framing: frame.into(),
        }))
    }
}
fn main() {
    new_methods_decode::run("miniz", adapter::factory);
}
