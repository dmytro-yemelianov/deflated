//! Research-only bounded encoded-cost parser. No production defaults change.
use deflate_core::tokens::Token;
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};

#[path = "support/cost_parse.rs"]
mod parser;

#[derive(Clone, Copy)]
enum Method {
    Preset(deflate_core::CompressionLevel),
    Parsed(parser::Settings, bool),
}

impl Method {
    fn parse(text: &str) -> Result<Self, String> {
        use deflate_core::CompressionLevel;
        match text {
            "balanced" => return Ok(Self::Preset(CompressionLevel::Balanced)),
            "fast" => return Ok(Self::Preset(CompressionLevel::Fast)),
            "best" => return Ok(Self::Preset(CompressionLevel::Best)),
            "exact" => {
                return Ok(Self::Parsed(
                    parser::Settings {
                        exact: true,
                        cost: true,
                        probes: 1,
                        block_bytes: 4096,
                    },
                    true,
                ));
            }
            _ => {}
        }
        let fields: Vec<_> = text.split(':').collect();
        let [kind, probes, block, emission] = fields.as_slice() else {
            return Err("method: exact or cost|longest:PROBES:BLOCK:fixed|auto".into());
        };
        let probes: usize = probes.parse().map_err(|_| "invalid probes")?;
        let block_bytes: usize = block.parse().map_err(|_| "invalid block")?;
        if !["cost", "longest"].contains(kind)
            || ![4, 16, 64].contains(&probes)
            || ![512, 4096, 16384].contains(&block_bytes)
            || !["fixed", "auto"].contains(emission)
        {
            return Err("invalid research parser settings".into());
        }
        Ok(Self::Parsed(
            parser::Settings {
                exact: false,
                cost: *kind != "longest",
                probes,
                block_bytes,
            },
            *emission == "fixed",
        ))
    }

    fn encode(self, raw: &[u8]) -> Vec<u8> {
        match self {
            Self::Preset(level) => deflate_core::deflate_with_level(raw, level),
            Self::Parsed(settings, fixed) => {
                let tokens = parser::parse(raw, settings);
                if fixed {
                    deflate_core::encode_fixed::emit_fixed(tokens)
                } else {
                    let packed =
                        deflate_core::encode_dynamic::emit_blocks(&tokens, |_| Some(16384));
                    let stored_bytes = raw.len() + raw.len().div_ceil(65535).max(1) * 5;
                    if stored_bytes < packed.len() {
                        deflate_core::deflate_stored(raw)
                    } else {
                        packed
                    }
                }
            }
        }
    }
}

fn sample(method: Method, raw: &[u8], minimum: Duration) -> f64 {
    let start = Instant::now();
    let mut count = 0_u32;
    loop {
        black_box(method.encode(black_box(raw)));
        count += 1;
        if start.elapsed() >= minimum {
            break;
        }
    }
    start.elapsed().as_nanos() as f64 / f64::from(count)
}

fn main() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() == 1 && args[0] == "--layout" {
        println!(
            "{{\"hash_bits\":{},\"window_bytes\":{},\"position_bits\":{},\"table_bytes\":{}}}",
            parser::HASH_BITS,
            parser::WINDOW,
            usize::BITS,
            ((1_usize << parser::HASH_BITS) + parser::WINDOW) * std::mem::size_of::<usize>()
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--tokens") {
        if args.len() != 3 {
            return Err("cost_parse --tokens INPUT METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let Method::Parsed(settings, _) = Method::parse(&args[2])? else {
            return Err("parsed method required".into());
        };
        let tokens = parser::parse(&raw, settings);
        assert_eq!(deflate_core::tokens::expand(&tokens).unwrap(), raw);
        let bits: u64 = 10
            + tokens
                .iter()
                .map(|t| match *t {
                    Token::Literal(b) => {
                        if b <= 143 {
                            8
                        } else {
                            9
                        }
                    }
                    Token::Match { len, dist } => parser::match_bits(len, dist),
                })
                .sum::<u64>();
        let packed = deflate_core::encode_fixed::emit_fixed(tokens.iter().copied());
        assert_eq!(packed.len() as u64, bits.div_ceil(8));
        assert_eq!(deflate_core::inflate(&packed).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
            raw
        );
        let mut encoded = Vec::new();
        for token in tokens {
            encoded.push(match token {
                Token::Literal(b) => format!("[\"l\",{b}]"),
                Token::Match { len, dist } => format!("[\"m\",{len},{dist}]"),
            });
        }
        println!(
            "{{\"fixed_bits\":{bits},\"packed_bytes\":{},\"tokens\":[{}],\"packed_hex\":\"{}\"}}",
            packed.len(),
            encoded.join(","),
            packed
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--check") {
        if args.len() != 3 {
            return Err("cost_parse --check RAW PACKED".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let packed = std::fs::read(&args[2]).map_err(|e| e.to_string())?;
        assert_eq!(deflate_core::inflate(&packed).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
            raw
        );
        return Ok(());
    }
    if args.len() != 5 {
        return Err("cost_parse CORPUS STREAMS ROUNDS MIN_MS METHOD".into());
    }
    let rounds: usize = args[2].parse().map_err(|_| "invalid rounds")?;
    let min_ms: u64 = args[3].parse().map_err(|_| "invalid duration")?;
    if rounds < 3 || min_ms == 0 {
        return Err("need three rounds and positive duration".into());
    }
    let method = Method::parse(&args[4])?;
    let baseline = Method::Preset(deflate_core::CompressionLevel::Balanced);
    let out = Path::new(&args[1]);
    std::fs::create_dir_all(out).map_err(|e| e.to_string())?;
    let mut files = std::fs::read_dir(&args[0])
        .map_err(|e| e.to_string())?
        .map(|e| e.map(|e| e.path()))
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    files.retain(|p| p.extension().is_some_and(|e| e == "raw"));
    files.sort();
    if files.is_empty() {
        return Err("empty corpus".into());
    }
    for (index, path) in files.iter().enumerate() {
        let name = path
            .file_name()
            .unwrap()
            .to_str()
            .ok_or("ASCII name required")?;
        if !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err("invalid input name".into());
        }
        let raw = std::fs::read(path).map_err(|e| e.to_string())?;
        let packed = method.encode(&raw);
        let base = baseline.encode(&raw);
        for stream in [&packed, &base] {
            assert_eq!(deflate_core::inflate(stream).unwrap(), raw);
            assert_eq!(
                miniz_oxide::inflate::decompress_to_vec(stream).unwrap(),
                raw
            );
        }
        assert_eq!(method.encode(&raw), packed, "nondeterministic output");
        std::fs::write(out.join(format!("{name}.deflate")), &packed).map_err(|e| e.to_string())?;
        std::fs::write(out.join(format!("{name}.baseline.deflate")), &base)
            .map_err(|e| e.to_string())?;
        let (mut samples, mut base_samples) = (Vec::new(), Vec::new());
        for round in 0..rounds {
            for turn in 0..2 {
                if (index + round + turn) % 2 == 0 {
                    samples.push(sample(method, &raw, Duration::from_millis(min_ms)));
                } else {
                    base_samples.push(sample(baseline, &raw, Duration::from_millis(min_ms)));
                }
            }
        }
        println!(
            "{{\"input\":{name:?},\"raw_bytes\":{},\"packed_bytes\":{},\"baseline_bytes\":{},\"samples_ns\":{samples:?},\"baseline_samples_ns\":{base_samples:?}}}",
            raw.len(),
            packed.len(),
            base.len()
        );
    }
    Ok(())
}
