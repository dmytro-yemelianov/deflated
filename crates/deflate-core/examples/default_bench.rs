//! Resident-input benchmark of the default encoder, built without research.
//! The same harness is compiled against the archived original core.
use std::hint::black_box;
use std::time::{Duration, Instant};

fn sample(mut operation: impl FnMut() -> Vec<u8>, minimum: Duration) -> (f64, u64) {
    let start = Instant::now();
    let mut count = 0;
    loop {
        black_box(operation());
        count += 1;
        let elapsed = start.elapsed();
        if elapsed >= minimum {
            return (elapsed.as_secs_f64() * 1e9 / count as f64, count);
        }
    }
}

fn main() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|s| s == "--memory") {
        if args.len() != 4 || args[3] != "balanced" {
            return Err("default_bench --memory INPUT OUTPUT balanced".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let packet = deflate_core::deflate(black_box(&raw));
        std::fs::write(&args[2], &packet).map_err(|e| e.to_string())?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{}}}",
            raw.len(),
            packet.len()
        );
        return Ok(());
    }
    if args.len() != 6 || !["warm", "cold"].contains(&args[0].as_str()) || args[4] != "balanced" {
        return Err("default_bench warm|cold INPUT OUT MIN_MS balanced ORDER".into());
    }
    let minimum: u64 = args[3].parse().map_err(|_| "invalid batch")?;
    let order: usize = args[5].parse().map_err(|_| "invalid order")?;
    if minimum == 0 || order > 1 {
        return Err("invalid batch or order".into());
    }
    let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
    // Input I/O precedes timing; cold performs no encode/decode priming.
    let start = Instant::now();
    let packet = deflate_core::deflate(black_box(&raw));
    let first_encode = start.elapsed().as_secs_f64() * 1e9;
    let start = Instant::now();
    let decoded = deflate_core::inflate(black_box(&packet)).map_err(|e| format!("{e:?}"))?;
    let first_decode = start.elapsed().as_secs_f64() * 1e9;
    assert_eq!(decoded, raw);
    assert_eq!(
        miniz_oxide::inflate::decompress_to_vec(&packet).unwrap(),
        raw
    );
    let (encode_ns, decode_ns, enc_count, dec_count) = if args[0] == "warm" {
        let duration = Duration::from_millis(minimum);
        let enc = sample(|| deflate_core::deflate(black_box(&raw)), duration);
        let dec = sample(
            || deflate_core::inflate(black_box(&packet)).unwrap(),
            duration,
        );
        (enc.0, dec.0, enc.1, dec.1)
    } else {
        (first_encode, first_decode, 1, 1)
    };
    std::fs::create_dir_all(&args[2]).map_err(|e| e.to_string())?;
    std::fs::write(
        std::path::Path::new(&args[2]).join("candidate.deflate"),
        &packet,
    )
    .map_err(|e| e.to_string())?;
    println!(
        "{{\"raw_bytes\":{},\"packed_bytes\":{},\"encode_ns\":{},\"decode_ns\":{},\"encode_iterations\":[{}],\"decode_iterations\":[{}]}}",
        raw.len(),
        packet.len(),
        encode_ns,
        decode_ns,
        enc_count,
        dec_count
    );
    Ok(())
}
