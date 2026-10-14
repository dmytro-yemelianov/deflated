//! CRC-only diagnostic. Allocation and input I/O are outside the timer.
use deflate_core::crc32::Crc32;
use std::{hint::black_box, time::Instant};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        return Err("crc_bench RAW_FILE MIN_NS".into());
    }
    let input = std::fs::read(&args[1])?;
    let minimum: u128 = args[2].parse()?;
    if minimum == 0 {
        return Err("zero duration".into());
    }
    let crc = Crc32::compute(&input);
    let start = Instant::now();
    let mut count = 0u64;
    loop {
        black_box(Crc32::compute(black_box(&input)));
        count += 1;
        let elapsed = start.elapsed().as_nanos();
        if elapsed >= minimum {
            let ns = elapsed as f64 / count as f64;
            println!("{{\"crc32\":{crc},\"ns\":{ns},\"iterations\":{count}}}");
            break;
        }
    }
    Ok(())
}
