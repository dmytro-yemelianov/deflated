//! Research-only measurement adapter for scripts/search_poc.py. This exposes
//! existing public methods, not arbitrary matcher parameters or a new preset.
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};

const NAMES: [&str; 11] = [
    "stored",
    "fast",
    "balanced",
    "best",
    "split256",
    "split1024",
    "split4096",
    "split16384",
    "miniz1",
    "miniz6",
    "miniz9",
];

fn encode(raw: &[u8], candidate: usize) -> Vec<u8> {
    use deflate_core::compress::deflate_with_split;
    use deflate_core::{CompressionLevel, deflate_with_level};
    match candidate {
        0 => deflate_core::deflate_stored(raw),
        1 => deflate_with_level(raw, CompressionLevel::Fast),
        2 => deflate_with_level(raw, CompressionLevel::Balanced),
        3 => deflate_with_level(raw, CompressionLevel::Best),
        4 => deflate_with_split(raw, |_| Some(256)),
        5 => deflate_with_split(raw, |_| Some(1024)),
        6 => deflate_with_split(raw, |_| Some(4096)),
        7 => deflate_with_split(raw, |_| Some(16384)),
        8 => miniz_oxide::deflate::compress_to_vec(raw, 1),
        9 => miniz_oxide::deflate::compress_to_vec(raw, 6),
        _ => miniz_oxide::deflate::compress_to_vec(raw, 9),
    }
}

fn sample(raw: &[u8], candidate: usize, minimum: Duration) -> f64 {
    let start = Instant::now();
    let mut count = 0_u32;
    loop {
        black_box(encode(black_box(raw), candidate));
        count += 1;
        let elapsed = start.elapsed();
        if elapsed >= minimum {
            return elapsed.as_secs_f64() * 1e9 / f64::from(count);
        }
    }
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    assert_eq!(args.len(), 4, "search CORPUS STREAMS ROUNDS MIN_MS");
    let corpus = Path::new(&args[0]);
    let output = Path::new(&args[1]);
    let rounds: usize = args[2].parse().expect("ROUNDS");
    let minimum = Duration::from_millis(args[3].parse().expect("MIN_MS"));
    assert!(rounds > 0 && !minimum.is_zero());
    let mut files: Vec<_> = std::fs::read_dir(corpus)
        .expect("corpus directory")
        .map(|e| e.expect("corpus entry").path())
        .filter(|p| p.extension().is_some_and(|e| e == "raw"))
        .collect();
    files.sort();
    assert!(!files.is_empty(), "empty corpus");
    for name in NAMES {
        std::fs::create_dir_all(output.join(name)).expect("streams directory");
    }
    for (index, file) in files.iter().enumerate() {
        let name = file.file_name().unwrap().to_str().expect("ASCII filename");
        assert!(
            name.bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        );
        let raw = std::fs::read(file).expect("input");
        let mut sizes = [0; NAMES.len()];
        let mut times: [Vec<f64>; NAMES.len()] = std::array::from_fn(|_| Vec::new());
        for (candidate, size) in sizes.iter_mut().enumerate() {
            let packed = encode(&raw, candidate);
            assert_eq!(deflate_core::inflate(&packed).unwrap(), raw);
            assert_eq!(
                miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
                raw
            );
            assert_eq!(encode(&raw, candidate), packed, "nondeterministic stream");
            *size = packed.len();
            std::fs::write(
                output
                    .join(NAMES[candidate])
                    .join(format!("{name}.deflate")),
                packed,
            )
            .expect("packed stream");
        }
        for round in 0..rounds {
            for offset in 0..NAMES.len() {
                let candidate = (round + index + offset) % NAMES.len();
                times[candidate].push(sample(&raw, candidate, minimum));
            }
        }
        for (candidate, samples) in times.iter().enumerate() {
            // Input names and candidate IDs have been restricted to JSON-safe
            // ASCII. Keep every round, rather than only a summary statistic.
            println!(
                "{{\"input\": {name:?}, \"candidate\": {:?}, \"raw_bytes\": {}, \
                 \"packed_bytes\": {}, \"samples_ns\": {samples:?}}}",
                NAMES[candidate],
                raw.len(),
                sizes[candidate]
            );
        }
    }
}
