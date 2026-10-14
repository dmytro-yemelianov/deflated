//! Paired portable-vs-accelerated CRC32 microbenchmark.
use std::{hint::black_box, time::Instant};

fn run(bytes: &[u8], iterations: usize, fast: bool) -> (u128, u32) {
    let start = Instant::now();
    let mut sum = 0u32;
    for _ in 0..iterations {
        let input = black_box(bytes);
        let crc = if fast {
            crc32fast::hash(input)
        } else {
            deflate_core::crc32::Crc32::compute(input)
        };
        sum = sum.wrapping_add(black_box(crc));
    }
    (start.elapsed().as_nanos(), sum)
}

fn main() {
    let sizes = [11usize, 64, 1024, 8192, 65536, 262144, 1048576];
    println!("size_index,sample,size,iterations,backend,ns_per_call,mb_per_s,checksum");
    for (size_index, size) in sizes.into_iter().enumerate() {
        let bytes = vec![0xA5; size];
        let iterations = ((8 * 1024 * 1024) / size).clamp(30, 1_000_000);
        for sample in 0..7 {
            for order in 0..2 {
                let fast = (size_index + sample + order) % 2 == 0;
                let (elapsed, checksum) = run(&bytes, iterations, fast);
                let ns_call = elapsed as f64 / iterations as f64;
                let mb_s = size as f64 * iterations as f64 / elapsed as f64 * 1e3;
                println!(
                    "{size_index},{sample},{size},{iterations},{},{ns_call:.2},{mb_s:.2},{checksum:08x}",
                    if fast { "crc32fast" } else { "deflated" }
                );
            }
        }
    }
}
