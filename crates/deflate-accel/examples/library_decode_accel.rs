//! Whole-buffer public API benchmark. Input I/O is outside the timer.
use std::{fs, hint::black_box, time::Instant};

/// Batched mode: smallest timed batch and its call cap.
const BATCH_NS: u128 = 100_000;
const MAX_BATCH: u64 = 1 << 20;

fn decode(packet: &[u8], frame: &str, expected: usize, out: &mut Vec<u8>) -> Result<(), String> {
    let mut decoder = deflate_accel::Decompressor::new();
    match frame {
        "raw" => {
            let result = decoder
                .inflate_into(packet, out, expected)
                .map_err(|e| format!("{e:?}"))?;
            if result.bytes_consumed != packet.len() {
                return Err("trailing input".into());
            }
        }
        "gzip" => {
            decoder
                .gunzip_into(packet, out, expected)
                .map_err(|e| format!("{e:?}"))?;
        }
        _ => return Err("invalid framing".into()),
    }
    if out.len() != expected {
        return Err("output size".into());
    }
    Ok(())
}

fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 9
        || args[2] != "core"
        || !matches!(
            args[1].as_str(),
            "cold" | "warm" | "reuse-warm" | "batched-warm"
        )
    {
        return Err("library_decode_accel cold|warm|reuse-warm|batched-warm core balanced raw|gzip PACKET OUTPUT MIN_NS EXPECTED".into());
    }
    let expected: usize = args[8].parse().map_err(|_| "expected size")?;
    let minimum: u128 = args[7].parse().map_err(|_| "duration")?;
    if expected > 64 << 20 || (args[1] != "cold" && minimum == 0) {
        return Err("limit or duration".into());
    }
    let packet = fs::read(&args[5]).map_err(|e| e.to_string())?;
    let start = Instant::now();
    let mut out = Vec::with_capacity(expected);
    decode(black_box(&packet), &args[4], expected, &mut out)?;
    let first = start.elapsed().as_nanos();
    fs::write(&args[6], &out).map_err(|e| e.to_string())?;
    let reuse = args[1] == "reuse-warm";
    let (mut duration, mut count) = (first as f64, 1u64);
    let mut batch = 0u64;
    if args[1] == "batched-warm" {
        // Batched timer (v15): fresh output (and decoder) per call as in
        // `warm`; calibrate untimed until one clock pair covers at least
        // 100 µs. The last output of each batch is compared outside the timer.
        let mut last = Vec::new();
        let timed_batch = |batch: u64, last: &mut Vec<u8>| -> Result<u128, String> {
            let start = Instant::now();
            for _ in 0..batch {
                let mut fresh = Vec::with_capacity(expected);
                decode(black_box(&packet), &args[4], expected, &mut fresh)?;
                *last = black_box(fresh);
            }
            Ok(start.elapsed().as_nanos())
        };
        batch = 1;
        while timed_batch(batch, &mut last)? < BATCH_NS && batch < MAX_BATCH {
            batch *= 2;
        }
        let mut elapsed = 0u128;
        count = 0;
        while elapsed < minimum {
            elapsed += timed_batch(batch, &mut last)?;
            count += batch;
            if last != out {
                return Err("batch output".into());
            }
        }
        duration = elapsed as f64 / count as f64;
    } else if args[1] != "cold" {
        let start = Instant::now();
        count = 0;
        loop {
            if reuse {
                decode(black_box(&packet), &args[4], expected, &mut out)?;
                black_box(&out);
            } else {
                let mut fresh = Vec::with_capacity(expected);
                decode(black_box(&packet), &args[4], expected, &mut fresh)?;
                drop(black_box(fresh));
            }
            count += 1;
            let elapsed = start.elapsed().as_nanos();
            if elapsed >= minimum {
                duration = elapsed as f64 / count as f64;
                break;
            }
        }
    }
    let context = if reuse {
        "reuse-output"
    } else {
        "fresh-decoder-only"
    };
    let batch_field = if batch > 0 {
        format!(",\"batch_calls\":{batch}")
    } else {
        String::new()
    };
    println!(
        "{{\"decode_ns\":{duration},\"first_decode_ns\":{first},\"decode_iterations\":{count},\"raw_bytes\":{},\"packed_bytes\":{},\"context\":\"{context}\",\"encoder_calls\":0{batch_field}}}",
        out.len(),
        packet.len()
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
