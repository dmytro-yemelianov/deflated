//! Corpus tuning benchmark. Samples median batch times, checks streams with
//! an independent decoder, and reports sizes alongside speed. No corpus data
//! is built into the binary. See scripts/tuning_corpus.py.

use std::hint::black_box;
use std::time::{Duration, Instant};

fn sample(mut f: impl FnMut() -> Vec<u8>, minimum: Duration) -> f64 {
    let start = Instant::now();
    let mut count = 0;
    loop {
        black_box(f());
        count += 1;
        if start.elapsed() >= minimum {
            return start.elapsed().as_secs_f64() * 1e9 / f64::from(count);
        }
    }
}

fn median(samples: &mut [f64]) -> f64 {
    samples.sort_by(f64::total_cmp);
    samples[samples.len() / 2]
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let dir = std::path::Path::new(args.first().expect("tune CORPUS [ROUNDS] [MIN_MS]"));
    let rounds: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(5);
    assert!(rounds > 0);
    let minimum = Duration::from_millis(args.get(2).and_then(|s| s.parse().ok()).unwrap_or(30));
    let level = match std::env::var("TUNE_LEVEL").as_deref() {
        Ok("fast") => deflate_core::CompressionLevel::Fast,
        Ok("best") => deflate_core::CompressionLevel::Best,
        _ => deflate_core::CompressionLevel::Balanced,
    };
    let mut files: Vec<_> = std::fs::read_dir(dir)
        .expect("corpus directory")
        .map(|e| e.expect("corpus entry").path())
        .filter(|p| p.extension().is_some_and(|e| e == "raw"))
        .collect();
    files.sort();
    println!("[");
    for (index, file) in files.iter().enumerate() {
        let raw = std::fs::read(file).expect("corpus input");
        let encode = |algorithm| match algorithm {
            0 => deflate_core::deflate_with_level(black_box(&raw), level),
            1 => miniz_oxide::deflate::compress_to_vec(black_box(&raw), 1),
            2 => miniz_oxide::deflate::compress_to_vec(black_box(&raw), 6),
            _ => miniz_oxide::deflate::compress_to_vec(black_box(&raw), 9),
        };
        let mut sizes = [0; 4];
        let mut times: [Vec<f64>; 4] = std::array::from_fn(|_| Vec::new());
        for (algorithm, size) in sizes.iter_mut().enumerate() {
            let out = encode(algorithm);
            assert_eq!(miniz_oxide::inflate::decompress_to_vec(&out).unwrap(), raw);
            assert_eq!(deflate_core::inflate(&out).unwrap(), raw);
            *size = out.len();
        }
        // Rotate order to distribute warm-up and temperature effects.
        for round in 0..rounds {
            for offset in 0..4 {
                let algorithm = (round + index + offset) % 4;
                times[algorithm].push(sample(|| encode(algorithm), minimum));
            }
        }
        print!(
            "  {{\"input\": {:?}, \"raw_bytes\": {}",
            file.file_name().unwrap().to_str().unwrap(),
            raw.len()
        );
        for (algorithm, name) in ["deflate_core", "miniz_l1", "miniz_l6", "miniz_l9"]
            .iter()
            .enumerate()
        {
            let ns = median(&mut times[algorithm]);
            print!(
                ", \"{name}_bytes\": {}, \"{name}_ns\": {:.0}, \"{name}_mb_s\": {:.3}",
                sizes[algorithm],
                ns,
                raw.len() as f64 / ns * 1e3
            );
        }
        println!("}}{}", if index + 1 < files.len() { "," } else { "" });
    }
    println!("]");
}
