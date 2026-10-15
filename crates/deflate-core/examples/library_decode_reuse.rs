//! Whole-buffer public API benchmark. Input I/O is outside the timer.
use std::{fs, hint::black_box, time::Instant};

/// Batched mode: smallest timed batch and its call cap.
const BATCH_NS: u128 = 100_000;
const MAX_BATCH: u64 = 1 << 20;

fn decode_reusing(
    decoder: &mut deflate_core::Decompressor,
    packet: &[u8],
    frame: &str,
    expected: usize,
    out: &mut Vec<u8>,
) -> Result<(), String> {
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
            "context-warm" | "context-cold" | "context-batched"
        )
    {
        return Err("library_decode_reuse context-cold|context-warm|context-batched core balanced raw|gzip PACKET OUTPUT MIN_NS EXPECTED".into());
    }
    let expected: usize = args[8].parse().map_err(|_| "expected size")?;
    let minimum: u128 = args[7].parse().map_err(|_| "duration")?;
    let cold = matches!(args[1].as_str(), "cold" | "context-cold");
    if expected > 64 << 20 || (!cold && minimum == 0) {
        return Err("limit or duration".into());
    }
    let packet = fs::read(&args[5]).map_err(|e| e.to_string())?;
    let start = Instant::now();
    let mut out = Vec::with_capacity(expected);
    let mut decoder = deflate_core::Decompressor::new();
    decode_reusing(
        &mut decoder,
        black_box(&packet),
        &args[4],
        expected,
        &mut out,
    )?;
    let first = start.elapsed().as_nanos();
    let (mut duration, mut count) = (first as f64, 1u64);
    let mut batch = 0u64;
    if args[1] == "context-batched" {
        // Batched timer (v15): calibrate untimed until one clock pair covers
        // at least 100 µs, then time whole batches. Every call still checks
        // its size; the bytes are compared after each batch, outside the timer.
        let reference = out.clone();
        batch = 1;
        loop {
            let start = Instant::now();
            for _ in 0..batch {
                decode_reusing(
                    &mut decoder,
                    black_box(&packet),
                    &args[4],
                    expected,
                    &mut out,
                )?;
                black_box(&out);
            }
            if start.elapsed().as_nanos() >= BATCH_NS || batch >= MAX_BATCH {
                break;
            }
            batch *= 2;
        }
        let mut elapsed = 0u128;
        count = 0;
        while elapsed < minimum {
            let start = Instant::now();
            for _ in 0..batch {
                decode_reusing(
                    &mut decoder,
                    black_box(&packet),
                    &args[4],
                    expected,
                    &mut out,
                )?;
                black_box(&out);
            }
            elapsed += start.elapsed().as_nanos();
            count += batch;
            if out != reference {
                return Err("batch output".into());
            }
        }
        duration = elapsed as f64 / count as f64;
    } else if !cold {
        let start = Instant::now();
        count = 0;
        loop {
            decode_reusing(
                &mut decoder,
                black_box(&packet),
                &args[4],
                expected,
                &mut out,
            )?;
            black_box(&out);
            count += 1;
            let elapsed = start.elapsed().as_nanos();
            if elapsed >= minimum {
                duration = elapsed as f64 / count as f64;
                break;
            }
        }
    }
    fs::write(&args[6], &out).map_err(|e| e.to_string())?;
    let context = "reuse-state-output";
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
