//! Conservative linked-size probe of one method plus the shared runtime parser.
#[cfg(feature = "research-tuning")]
#[allow(dead_code)]
#[path = "support/final_bench.rs"]
mod worker;
#[cfg(feature = "research-tuning")]
fn main() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 2 {
        return Err("final_size INPUT OUTPUT".into());
    }
    worker::memory(
        option_env!("DEFLATED_FINAL_METHOD").unwrap_or("balanced"),
        &args[0],
        &args[1],
    )
}
#[cfg(not(feature = "research-tuning"))]
fn main() {
    eprintln!("final_size requires --features research-tuning");
}
