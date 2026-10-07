//! Process startup and input/output I/O are outside the codec timers.
use crate::Result;
use std::{fs, hint::black_box, time::Instant};

pub const LIMIT: usize = 64 << 20;
pub trait Engine {
    fn encode(&self, raw: &[u8]) -> Result<Vec<u8>>;
    fn decode(&self, packet: &[u8], expected: usize) -> Result<Vec<u8>>;
}
fn read(path: &str) -> Result<Vec<u8>> {
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > LIMIT as u64 {
        return Err("input limit".into());
    }
    fs::read(path).map_err(|e| e.to_string())
}
fn write(path: &str, data: &[u8]) -> Result<()> {
    fs::write(path, data).map_err(|e| e.to_string())
}
fn sample<F>(minimum: u128, mut call: F) -> Result<(f64, u64)>
where
    F: FnMut() -> Result<Vec<u8>>,
{
    let start = Instant::now();
    let mut count = 0;
    loop {
        // Dropping every result is paid. No cached checksum, dictionary, packet,
        // output capacity, or data history is supplied to the encoder.
        drop(black_box(call()?));
        count += 1;
        let elapsed = start.elapsed().as_nanos();
        if elapsed >= minimum {
            return Ok((elapsed as f64 / count as f64, count));
        }
    }
}
pub fn run<F>(codec: &str, version_json: &str, factory: F)
where
    F: Fn(&str, &str) -> Result<Box<dyn Engine>>,
{
    let args: Vec<_> = std::env::args().collect();
    if args.len() == 2 && args[1] == "--version" {
        println!("{version_json}");
        return;
    }
    if args.len() == 2 && args[1] == "--clock" {
        let start = Instant::now();
        let mut previous = start.elapsed().as_nanos();
        let mut smallest = u128::MAX;
        for _ in 0..10000 {
            let now = start.elapsed().as_nanos();
            if now > previous {
                smallest = smallest.min(now - previous);
            }
            previous = now;
        }
        println!("{{\"minimum_observed_clock_step_ns\":{smallest}}}");
        return;
    }
    if let Err(error) = execute(&args, codec, factory) {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
fn execute<F>(args: &[String], codec: &str, factory: F) -> Result<()>
where
    F: Fn(&str, &str) -> Result<Box<dyn Engine>>,
{
    if !(args.len() == 9 || (args.len() == 10 && args[1] == "reset-check")) || args[2] != codec {
        return Err("worker MODE CODEC LEVEL FRAMING INPUT OUTPUT MIN_NS EXPECTED_RAW [SECOND_INPUT for reset-check]".into());
    }
    let mode = args[1].as_str();
    let minimum: u128 = args[7].parse().map_err(|_| "invalid duration")?;
    let expected: usize = args[8].parse().map_err(|_| "invalid expected size")?;
    if expected > LIMIT {
        return Err("output limit".into());
    }
    let engine = factory(&args[3], &args[4])?;
    let input = read(&args[5])?;
    if mode == "reset-check" {
        if args.len() != 10 {
            return Err("missing second input".into());
        }
        let second = read(&args[9])?;
        let original = engine.encode(&input)?;
        let b = engine.encode(&second)?;
        for (raw, packet) in [(&input, &original), (&second, &b), (&input, &original)] {
            let actual = engine.encode(raw)?;
            if actual != *packet || engine.decode(&actual, raw.len())? != *raw {
                return Err("A-B-A identity".into());
            }
        }
        write(&args[6], &b)?;
        println!(
            "{{\"reset_check\":\"passed-stateless-A-B-A\",\"encode_init_ns\":0,\"decode_init_ns\":0}}"
        );
        return Ok(());
    }
    if matches!(mode, "decode" | "memory-decode") {
        let raw = engine.decode(&input, expected)?;
        write(&args[6], &raw)?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{}}}",
            raw.len(),
            input.len()
        );
        return Ok(());
    }
    if !matches!(
        mode,
        "encode" | "memory-encode" | "cold" | "warm" | "reuse-cold" | "reuse-warm"
    ) {
        return Err("invalid mode".into());
    }
    let start = Instant::now();
    let packet = engine.encode(black_box(&input))?;
    let first_encode = start.elapsed().as_nanos();
    if matches!(mode, "encode" | "memory-encode") {
        write(&args[6], &packet)?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{}}}",
            input.len(),
            packet.len()
        );
        return Ok(());
    }
    let start = Instant::now();
    let decoded = engine.decode(black_box(&packet), input.len())?;
    let first_decode = start.elapsed().as_nanos();
    if decoded != input {
        return Err("roundtrip mismatch".into());
    }
    drop(decoded);
    let (mut enc, mut dec, mut enc_count, mut dec_count) =
        (first_encode as f64, first_decode as f64, 1, 1);
    if matches!(mode, "warm" | "reuse-warm") {
        if minimum == 0 {
            return Err("zero sample duration".into());
        }
        (enc, enc_count) = sample(minimum, || engine.encode(black_box(&input)))?;
        (dec, dec_count) = sample(minimum, || engine.decode(black_box(&packet), input.len()))?;
    }
    let context = if mode.starts_with("reuse-") {
        "fresh-no-reuse-adapter"
    } else {
        "fresh"
    };
    write(&args[6], &packet)?;
    println!(
        "{{\"raw_bytes\":{},\"packed_bytes\":{},\"encode_ns\":{enc},\"decode_ns\":{dec},\"first_encode_ns\":{first_encode},\"first_decode_ns\":{first_decode},\"encode_iterations\":{enc_count},\"decode_iterations\":{dec_count},\"context\":\"{context}\",\"encode_init_ns\":0,\"decode_init_ns\":0}}",
        input.len(),
        packet.len()
    );
    Ok(())
}
