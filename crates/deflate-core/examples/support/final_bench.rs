//! S9 measurement paths. All methods include fresh per-call encoder allocations.
use deflate_core::research::{Config, Index};
use std::hint::black_box;
use std::time::{Duration, Instant};
#[path = "policy.rs"]
mod policy;
#[derive(Clone, Copy)]
pub(crate) enum BaseMethod {
    Preset(deflate_core::CompressionLevel),
    Stored,
    Configured(Config),
    Reference(u8),
}

impl BaseMethod {
    fn parse(text: &str) -> Result<Self, String> {
        use deflate_core::CompressionLevel;
        match text {
            "fast" => return Ok(Self::Preset(CompressionLevel::Fast)),
            "balanced" => return Ok(Self::Preset(CompressionLevel::Balanced)),
            "best" => return Ok(Self::Preset(CompressionLevel::Best)),
            "stored" => return Ok(Self::Stored),
            "miniz1" => return Ok(Self::Reference(1)),
            "miniz6" => return Ok(Self::Reference(6)),
            "miniz9" => return Ok(Self::Reference(9)),
            _ => {}
        }
        let fields: Vec<_> = text.split(':').collect();
        if fields.len() != 6 || fields[0] != "config" {
            return Err(
                "expected a preset or config:PROBES:LAZY(0/1):TAIL:INDEX:BLOCK_TOKENS".into(),
            );
        }
        let integer = |n: usize| {
            fields[n]
                .parse()
                .map_err(|_| "invalid unsigned integer".to_string())
        };
        let lazy = match fields[2] {
            "0" => false,
            "1" => true,
            _ => return Err("lazy must be 0 or 1".into()),
        };
        let index = match fields[4] {
            "dual" => Index::Dual,
            "trigram" => Index::Trigram,
            _ => return Err("index must be dual or trigram".into()),
        };
        Config::new(integer(1)?, lazy, integer(3)?, index, integer(5)?)
            .map(Self::Configured)
            .map_err(|e| e.to_string())
    }

    fn encode(self, raw: &[u8]) -> Vec<u8> {
        match self {
            Self::Preset(level) => deflate_core::deflate_with_level(raw, level),
            Self::Stored => deflate_core::deflate_stored(raw),
            Self::Configured(config) => deflate_core::research::deflate(raw, config),
            Self::Reference(level) => miniz_oxide::deflate::compress_to_vec(raw, level),
        }
    }
}

enum Method {
    Base(BaseMethod),
    Policy(policy::Policy),
}
impl Method {
    fn parse(text: &str) -> Result<Self, String> {
        if let Some(path) = text.strip_prefix("policy@") {
            return policy::Policy::load(path).map(Self::Policy);
        }
        BaseMethod::parse(text).map(Self::Base)
    }
    fn encode(&self, raw: &[u8]) -> Vec<u8> {
        match self {
            Self::Base(method) => method.encode(raw),
            Self::Policy(selector) => selector.choose(raw).encode(raw),
        }
    }
}

fn sample(mut operation: impl FnMut() -> Vec<u8>, minimum: Duration) -> (f64, u64) {
    let start = Instant::now();
    let mut count = 0_u64;
    loop {
        black_box(operation());
        count += 1;
        let elapsed = start.elapsed();
        if elapsed >= minimum {
            return (elapsed.as_secs_f64() * 1e9 / count as f64, count);
        }
    }
}

fn write_packets(out: &str, packet: &[u8], baseline: Option<&[u8]>) -> Result<(), String> {
    std::fs::create_dir_all(out).map_err(|e| e.to_string())?;
    std::fs::write(std::path::Path::new(out).join("candidate.deflate"), packet)
        .map_err(|e| e.to_string())?;
    if let Some(baseline) = baseline {
        std::fs::write(std::path::Path::new(out).join("baseline.deflate"), baseline)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn memory(method: &str, input: &str, output: &str) -> Result<(), String> {
    let raw = std::fs::read(input).map_err(|e| e.to_string())?;
    let packet = Method::parse(method)?.encode(black_box(&raw));
    std::fs::write(output, &packet).map_err(|e| e.to_string())?;
    println!(
        "{{\"raw_bytes\":{},\"packed_bytes\":{}}}",
        raw.len(),
        packet.len()
    );
    Ok(())
}

pub fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|a| a == "--memory") {
        if args.len() != 4 {
            return Err("final_bench --memory INPUT OUTPUT METHOD".into());
        }
        return memory(&args[3], &args[1], &args[2]);
    }
    if args.len() != 6 {
        return Err("final_bench warm|cold INPUT OUT MIN_MS METHOD ORDER".into());
    }
    if !["warm", "cold"].contains(&args[0].as_str()) {
        return Err("invalid workload".into());
    }
    let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
    let method = Method::parse(&args[4])?;
    let min_ms: u64 = args[3].parse().map_err(|_| "invalid batch")?;
    let order: usize = args[5].parse().map_err(|_| "invalid order")?;
    if min_ms == 0 || order > 1 {
        return Err("invalid batch or order".into());
    }
    if args[0] == "cold" {
        // No encode/decode priming. The candidate has a fresh process/allocator;
        // input pages are resident after I/O, and parsing the resident policy
        // precedes the timer. Process startup and disk I/O are excluded.
        let start = Instant::now();
        let packet = method.encode(black_box(&raw));
        let encode_ns = start.elapsed().as_nanos();
        let start = Instant::now();
        let decoded = deflate_core::inflate(black_box(&packet)).map_err(|e| format!("{e:?}"))?;
        let decode_ns = start.elapsed().as_nanos();
        assert_eq!(decoded, raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&packet).unwrap(),
            raw
        );
        write_packets(&args[2], &packet, None)?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"encode_ns\":{encode_ns},\"decode_ns\":{decode_ns}}}",
            raw.len(),
            packet.len()
        );
        return Ok(());
    }
    let baseline = Method::Base(BaseMethod::Preset(deflate_core::CompressionLevel::Balanced));
    let packet = method.encode(&raw);
    let base = baseline.encode(&raw);
    for packed in [&packet, &base] {
        assert_eq!(deflate_core::inflate(packed).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(packed).unwrap(),
            raw
        );
    }
    assert_eq!(method.encode(&raw), packet);
    let minimum = Duration::from_millis(min_ms);
    let (mut enc, mut dec) = ([(0.0, 0); 2], [(0.0, 0); 2]);
    for turn in 0..2 {
        let index = (order + turn) % 2;
        enc[index] = if index == 0 {
            sample(|| method.encode(black_box(&raw)), minimum)
        } else {
            sample(|| baseline.encode(black_box(&raw)), minimum)
        };
    }
    for turn in 0..2 {
        let index = (order + turn) % 2;
        let stream = if index == 0 { &packet } else { &base };
        dec[index] = sample(
            || deflate_core::inflate(black_box(stream)).unwrap(),
            minimum,
        );
    }
    write_packets(&args[2], &packet, Some(&base))?;
    println!(
        "{{\"raw_bytes\":{},\"packed_bytes\":{},\"baseline_bytes\":{},\"encode_ns\":{},\"baseline_encode_ns\":{},\"decode_ns\":{},\"baseline_decode_ns\":{},\"encode_iterations\":[{},{}],\"decode_iterations\":[{},{}]}}",
        raw.len(),
        packet.len(),
        base.len(),
        enc[0].0,
        enc[1].0,
        dec[0].0,
        dec[1].0,
        enc[0].1,
        enc[1].1,
        dec[0].1,
        dec[1].1
    );
    Ok(())
}
