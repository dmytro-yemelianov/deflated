//! In-process decode throughput, `deflate-core` against `miniz_oxide`.
//!
//! Driven by `scripts/perf_report.sh`, which generates the corpus and keeps
//! the JSON this prints. Timing in-process matters: the CLI spends a few
//! milliseconds on process start and I/O, which hides most of a stored
//! block's cost.
//!
//! usage: perf CORPUS_DIR [REPS]
//!        perf compress CORPUS_DIR [REPS]   (encoder ratio and speed)
//! With `PERF_ONLY=name.deflate` it decodes that one file in a loop for
//! `PERF_SECS` seconds instead, so a sampling profiler has something to see.

use std::time::{Duration, Instant};

fn best_of<F: FnMut()>(reps: u32, mut f: F) -> Duration {
    (0..reps)
        .map(|_| {
            let t = Instant::now();
            f();
            t.elapsed()
        })
        .min()
        .unwrap_or_default()
}

/// Encoder measurement: `deflate_core::deflate` against `miniz_oxide`
/// levels 1 and 6 on each `.raw` payload. Every stream is decoded back with
/// `deflate-core` and compared before it is timed.
fn compress_mode(dir: &std::path::Path, reps: u32) {
    let mut names: Vec<String> = std::fs::read_dir(dir)
        .expect("read corpus dir")
        .filter_map(|e| e.ok()?.file_name().into_string().ok())
        .filter(|n| n.ends_with(".raw"))
        .collect();
    names.sort();
    println!("[");
    for (i, name) in names.iter().enumerate() {
        let raw = std::fs::read(dir.join(name)).expect("read input");
        let mbps = |t: Duration| raw.len() as f64 / t.as_secs_f64() / 1e6;
        let ours = deflate_core::deflate(&raw);
        assert!(
            deflate_core::inflate(&ours).expect("decode ours") == raw,
            "{name}: our stream does not round-trip"
        );
        let t_ours = best_of(reps, || {
            std::hint::black_box(deflate_core::deflate(std::hint::black_box(&raw)));
        });
        let mut fields = format!(
            "\"input\": \"{name}\", \"raw_bytes\": {}, \"deflate_core_bytes\": {}, \
             \"deflate_core_ratio\": {:.4}, \"deflate_core_mb_s\": {:.1}",
            raw.len(),
            ours.len(),
            ours.len() as f64 / raw.len() as f64,
            mbps(t_ours)
        );
        for level in [1u8, 6] {
            let theirs = miniz_oxide::deflate::compress_to_vec(&raw, level);
            assert!(
                deflate_core::inflate(&theirs).expect("decode miniz") == raw,
                "{name}: miniz_oxide level {level} does not round-trip"
            );
            let t = best_of(reps, || {
                std::hint::black_box(miniz_oxide::deflate::compress_to_vec(
                    std::hint::black_box(&raw),
                    level,
                ));
            });
            fields += &format!(
                ", \"miniz_l{level}_bytes\": {}, \"miniz_l{level}_ratio\": {:.4}, \
                 \"miniz_l{level}_mb_s\": {:.1}",
                theirs.len(),
                theirs.len() as f64 / raw.len() as f64,
                mbps(t)
            );
        }
        println!(
            "  {{{fields}}}{}",
            if i + 1 < names.len() { "," } else { "" }
        );
    }
    println!("]");
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("compress") {
        args.remove(0);
        let dir = std::path::PathBuf::from(args.first().expect("usage: perf compress DIR [REPS]"));
        let reps: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(5);
        compress_mode(&dir, reps);
        return;
    }
    let dir = std::path::PathBuf::from(args.first().expect("usage: perf CORPUS_DIR [REPS]"));
    let reps: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(15);

    if let Ok(only) = std::env::var("PERF_ONLY") {
        let input = std::fs::read(dir.join(&only)).expect("read input");
        let secs: u64 = std::env::var("PERF_SECS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(10);
        let end = Instant::now() + Duration::from_secs(secs);
        let mut n = 0u64;
        while Instant::now() < end {
            std::hint::black_box(deflate_core::inflate(&input).expect("decode"));
            n += 1;
        }
        eprintln!("{only}: {n} decodes");
        return;
    }

    let mut names: Vec<String> = std::fs::read_dir(&dir)
        .expect("read corpus dir")
        .filter_map(|e| e.ok()?.file_name().into_string().ok())
        .filter(|n| n.ends_with(".deflate"))
        .collect();
    names.sort();

    println!("[");
    for (i, name) in names.iter().enumerate() {
        let input = std::fs::read(dir.join(name)).expect("read input");
        let raw_name = format!("{}.raw", name.split('.').next().unwrap_or(""));
        let expected = std::fs::read(dir.join(raw_name)).expect("read expected output");

        // Correctness first: a fast wrong answer is not a measurement.
        let ours = deflate_core::inflate(&input).expect("deflate-core decode");
        let theirs = miniz_oxide::inflate::decompress_to_vec(&input).expect("miniz_oxide decode");
        assert!(
            ours == expected && theirs == expected,
            "{name}: output mismatch"
        );

        let t_ours = best_of(reps, || {
            std::hint::black_box(deflate_core::inflate(std::hint::black_box(&input)).ok());
        });
        let t_ref = best_of(reps, || {
            std::hint::black_box(
                miniz_oxide::inflate::decompress_to_vec(std::hint::black_box(&input)).ok(),
            );
        });
        let mbps = |t: Duration| expected.len() as f64 / t.as_secs_f64() / 1e6;
        println!(
            "  {{\"input\": \"{name}\", \"compressed_bytes\": {}, \"decompressed_bytes\": {}, \
             \"deflate_core_ns\": {}, \"miniz_oxide_ns\": {}, \
             \"deflate_core_mb_s\": {:.1}, \"miniz_oxide_mb_s\": {:.1}, \"slowdown\": {:.2}}}{}",
            input.len(),
            expected.len(),
            t_ours.as_nanos(),
            t_ref.as_nanos(),
            mbps(t_ours),
            mbps(t_ref),
            t_ours.as_secs_f64() / t_ref.as_secs_f64(),
            if i + 1 < names.len() { "," } else { "" }
        );
    }
    println!("]");
}
