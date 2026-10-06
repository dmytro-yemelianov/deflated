//! Serial paired measurement worker for scripts/search_cpu.py.
use deflate_core::research::{Config, Index};
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};

#[derive(Clone, Copy)]
enum Method {
    Preset(deflate_core::CompressionLevel),
    Stored,
    Configured(Config),
}

impl Method {
    fn parse(text: &str) -> Result<Self, String> {
        use deflate_core::CompressionLevel;
        match text {
            "fast" => return Ok(Self::Preset(CompressionLevel::Fast)),
            "balanced" => return Ok(Self::Preset(CompressionLevel::Balanced)),
            "best" => return Ok(Self::Preset(CompressionLevel::Best)),
            "stored" => return Ok(Self::Stored),
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
        }
    }
}

fn sample(mut encode: impl FnMut() -> Vec<u8>, minimum: Duration) -> f64 {
    let start = Instant::now();
    let mut count = 0_u32;
    loop {
        black_box(encode());
        count += 1;
        let elapsed = start.elapsed();
        if elapsed >= minimum {
            return elapsed.as_secs_f64() * 1e9 / f64::from(count);
        }
    }
}

fn main() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 5 {
        return Err("tune_config CORPUS STREAMS ROUNDS MIN_MS METHOD".into());
    }
    let rounds: usize = args[2].parse().map_err(|_| "invalid rounds")?;
    let min_ms = args[3].parse().map_err(|_| "invalid batch duration")?;
    if rounds < 3 || min_ms == 0 {
        return Err("need at least three rounds and positive batch duration".into());
    }
    let method = Method::parse(&args[4])?;
    let output = Path::new(&args[1]);
    std::fs::create_dir_all(output).map_err(|e| e.to_string())?;
    let mut files: Vec<_> = std::fs::read_dir(&args[0])
        .map_err(|e| e.to_string())?
        .map(|e| e.map(|e| e.path()))
        .collect::<Result<_, _>>()
        .map_err(|e| e.to_string())?;
    files.retain(|p| p.extension().is_some_and(|e| e == "raw"));
    files.sort();
    if files.is_empty() {
        return Err("empty corpus".into());
    }
    for (file_index, file) in files.iter().enumerate() {
        let name = file
            .file_name()
            .unwrap()
            .to_str()
            .ok_or("ASCII input names required")?;
        if !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err("invalid input name".into());
        }
        let raw = std::fs::read(file).map_err(|e| e.to_string())?;
        let packed = method.encode(&raw);
        assert_eq!(deflate_core::inflate(&packed).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
            raw
        );
        assert_eq!(method.encode(&raw), packed, "nondeterministic output");
        std::fs::write(output.join(format!("{name}.deflate")), &packed)
            .map_err(|e| e.to_string())?;
        let baseline =
            deflate_core::deflate_with_level(&raw, deflate_core::CompressionLevel::Balanced);
        let mut candidate_ns = Vec::new();
        let mut baseline_ns = Vec::new();
        for round in 0..rounds {
            for offset in 0..2 {
                if (file_index + round + offset) % 2 == 0 {
                    candidate_ns.push(sample(
                        || method.encode(black_box(&raw)),
                        Duration::from_millis(min_ms),
                    ));
                } else {
                    baseline_ns.push(sample(
                        || {
                            deflate_core::deflate_with_level(
                                black_box(&raw),
                                deflate_core::CompressionLevel::Balanced,
                            )
                        },
                        Duration::from_millis(min_ms),
                    ));
                }
            }
        }
        println!(
            "{{\"input\": {name:?}, \"raw_bytes\": {}, \"packed_bytes\": {}, \"baseline_bytes\": {}, \"samples_ns\": {candidate_ns:?}, \"baseline_samples_ns\": {baseline_ns:?}}}",
            raw.len(),
            packed.len(),
            baseline.len()
        );
    }
    Ok(())
}
