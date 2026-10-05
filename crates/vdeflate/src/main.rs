//! Minimal CLI. File I/O, argument parsing and process exit are outside the
//! verification boundary (spec §6). Task 23 gives this real behavior.
fn main() {
    eprintln!(
        "vdeflate {}: not yet implemented",
        env!("CARGO_PKG_VERSION")
    );
    std::process::exit(2);
}
