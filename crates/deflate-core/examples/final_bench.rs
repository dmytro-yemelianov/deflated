//! Final research measurement worker, available only with research-tuning.
#[cfg(feature = "research-tuning")]
#[path = "support/final_bench.rs"]
mod worker;
#[cfg(feature = "research-tuning")]
fn main() -> Result<(), String> {
    worker::run()
}
#[cfg(not(feature = "research-tuning"))]
fn main() {
    eprintln!("final_bench requires --features research-tuning");
}
