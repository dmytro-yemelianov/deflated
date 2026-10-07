//! Decoder-only resident-input timers, with no preceding encode in this process.
#![forbid(unsafe_code)]
use new_methods_bench::{Result, worker::Engine};
use std::{fs, hint::black_box, time::Instant};

const LIMIT: usize = 64 << 20;

pub fn run<F>(codec: &str, factory: F)
where
    F: Fn(&str, &str) -> Result<Box<dyn Engine>>,
{
    let args: Vec<_> = std::env::args().collect();
    if let Err(error) = execute(&args, codec, factory) {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

fn execute<F>(args: &[String], codec: &str, factory: F) -> Result<()>
where
    F: Fn(&str, &str) -> Result<Box<dyn Engine>>,
{
    if args.len() != 9 || args[2] != codec || !matches!(args[1].as_str(), "cold" | "warm") {
        return Err(
            "decode worker cold|warm CODEC LEVEL FRAMING PACKET OUTPUT MIN_NS EXPECTED_RAW".into(),
        );
    }
    let minimum: u128 = args[7].parse().map_err(|_| "invalid duration")?;
    let expected: usize = args[8].parse().map_err(|_| "invalid expected size")?;
    if expected > LIMIT || (args[1] == "warm" && minimum == 0) {
        return Err("output limit or zero sample duration".into());
    }
    if fs::metadata(&args[5]).map_err(|e| e.to_string())?.len() > LIMIT as u64 {
        return Err("input limit".into());
    }
    let packet = fs::read(&args[5]).map_err(|e| e.to_string())?;
    let engine = factory(&args[3], &args[4])?; // Immutable settings only.
    let start = Instant::now();
    let decoded = engine.decode(black_box(&packet), expected)?;
    let first = start.elapsed().as_nanos();
    if decoded.len() != expected {
        return Err("output size".into());
    }
    let (mut duration, mut count) = (first as f64, 1u64);
    if args[1] == "warm" {
        let start = Instant::now();
        count = 0;
        loop {
            // All codec state and output allocation/destruction are paid per call.
            drop(black_box(engine.decode(black_box(&packet), expected)?));
            count += 1;
            let elapsed = start.elapsed().as_nanos();
            if elapsed >= minimum {
                duration = elapsed as f64 / count as f64;
                break;
            }
        }
    }
    fs::write(&args[6], &decoded).map_err(|e| e.to_string())?;
    println!(
        "{{\"raw_bytes\":{},\"packed_bytes\":{},\"decode_ns\":{duration},\"first_decode_ns\":{first},\"decode_iterations\":{count},\"context\":\"fresh-decoder-only\",\"encoder_calls\":0,\"decode_init_ns\":0}}",
        decoded.len(),
        packet.len()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct DecodeOnly;
    impl Engine for DecodeOnly {
        fn encode(&self, _: &[u8]) -> Result<Vec<u8>> {
            panic!("the decoder timer must never invoke an encoder");
        }
        fn decode(&self, packet: &[u8], expected: usize) -> Result<Vec<u8>> {
            if packet.len() != expected {
                return Err("test size".into());
            }
            Ok(packet.to_vec())
        }
    }
    #[test]
    fn cold_and_warm_do_not_encode() {
        let directory = std::env::temp_dir().join(format!("decoder-only-{}", std::process::id()));
        fs::create_dir(&directory).unwrap();
        let input = directory.join("packet");
        let output = directory.join("out");
        fs::write(&input, b"abc").unwrap();
        for mode in ["cold", "warm"] {
            let args: Vec<String> = [
                "decoder",
                mode,
                "test",
                "0",
                "raw",
                input.to_str().unwrap(),
                output.to_str().unwrap(),
                "2000000",
                "3",
            ]
            .into_iter()
            .map(String::from)
            .collect();
            execute(&args, "test", |_, _| Ok(Box::new(DecodeOnly))).unwrap();
            assert_eq!(fs::read(&output).unwrap(), b"abc");
        }
        fs::remove_dir_all(directory).unwrap();
    }
}
