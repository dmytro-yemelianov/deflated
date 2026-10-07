//! Research-only alignment-aware mixed emission. No production defaults change.
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};
#[path = "support/mixed_blocks.rs"]
mod mixed;

#[derive(Clone, Copy)]
enum Method {
    Preset(deflate_core::CompressionLevel),
    Mixed(deflate_core::CompressionLevel, usize, bool),
}
impl Method {
    fn parse(text: &str) -> Result<Self, String> {
        use deflate_core::CompressionLevel;
        fn level(s: &str) -> Result<CompressionLevel, String> {
            match s {
                "fast" => Ok(CompressionLevel::Fast),
                "balanced" => Ok(CompressionLevel::Balanced),
                "best" => Ok(CompressionLevel::Best),
                _ => Err("invalid preset".into()),
            }
        }
        if !text.contains(':') {
            return Ok(Self::Preset(level(text)?));
        }
        let fields: Vec<_> = text.split(':').collect();
        let [kind, preset, count] = fields.as_slice() else {
            return Err("mixed|compressed:PRESET:TOKENS".into());
        };
        let count: usize = count.parse().map_err(|_| "invalid token count")?;
        if !["mixed", "compressed"].contains(kind) || ![1024, 4096, 16384].contains(&count) {
            return Err("invalid research block settings".into());
        }
        Ok(Self::Mixed(level(preset)?, count, *kind == "mixed"))
    }
    fn encode(self, raw: &[u8]) -> Vec<u8> {
        match self {
            Self::Preset(level) => deflate_core::deflate_with_level(raw, level),
            Self::Mixed(level, count, stored) => mixed::encode(raw, level, count, stored).packed,
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
    if args.first().is_some_and(|a| a == "--stored-probe") {
        if args.len() != 3 {
            return Err("mixed_blocks --stored-probe RAW PREFIX_COUNT".into());
        }
        let count: usize = args[2].parse().map_err(|_| "invalid prefix")?;
        if count >= 8 {
            return Err("invalid prefix".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let (packed, offset) = mixed::stored_probe(&raw, count);
        let expected = [vec![144; count], raw].concat();
        assert_eq!(deflate_core::inflate(&packed).unwrap(), expected);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
            expected
        );
        println!(
            "{{\"offset\":{offset},\"packed_hex\":\"{}\"}}",
            packed
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--plan") {
        if args.len() != 3 {
            return Err("mixed_blocks --plan START FIXED,DYNAMIC|_,RAW;...".into());
        }
        let start: usize = args[1].parse().map_err(|_| "invalid offset")?;
        if start >= 8 {
            return Err("invalid offset".into());
        }
        let mut costs = Vec::new();
        for part in args[2].split(';') {
            let values: Vec<_> = part.split(',').collect();
            let [fixed, dynamic, raw] = values.as_slice() else {
                return Err("invalid cost vector".into());
            };
            let fixed: usize = fixed.parse().map_err(|_| "invalid fixed cost")?;
            let raw: usize = raw.parse().map_err(|_| "invalid raw bytes")?;
            let dynamic = if *dynamic == "_" {
                None
            } else {
                Some(
                    dynamic
                        .parse::<usize>()
                        .map_err(|_| "invalid dynamic cost")?,
                )
            };
            if fixed == 0
                || fixed > 1_000_000
                || raw > 1_000_000
                || dynamic.is_some_and(|v| v == 0 || v > 1_000_000)
                || costs.len() >= 16
            {
                return Err("cost probe outside limits".into());
            }
            costs.push((fixed, dynamic, raw));
        }
        let (bits, kinds) = mixed::plan(&costs, true, start);
        println!(
            "{{\"bits\":{bits},\"kinds\":{:?}}}",
            kinds.iter().map(|k| format!("{k:?}")).collect::<Vec<_>>()
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--inspect") {
        if args.len() != 3 {
            return Err("mixed_blocks --inspect RAW METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let Method::Mixed(level, count, stored) = Method::parse(&args[2])? else {
            return Err("mixed policy required".into());
        };
        let evidence = mixed::encode(&raw, level, count, stored);
        assert_eq!(deflate_core::inflate(&evidence.packed).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&evidence.packed).unwrap(),
            raw
        );
        let blocks: Vec<_> = evidence.blocks.iter().map(|(raw, fixed, dynamic, kind, offset, actual)| {
            let dynamic = dynamic.map_or("null".to_string(), |n| n.to_string());
            format!("{{\"raw_bytes\":{raw},\"fixed_bits\":{fixed},\"dynamic_bits\":{dynamic},\"kind\":\"{kind:?}\",\"start_offset\":{offset},\"emitted_bits\":{actual}}}")
        }).collect();
        println!(
            "{{\"planned_bits\":{},\"emitted_bits\":{},\"fallback\":{},\"blocks\":[{}],\"packed_hex\":\"{}\"}}",
            evidence.planned_bits,
            evidence.emitted_bits,
            evidence.fallback,
            blocks.join(","),
            evidence
                .packed
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--check") {
        if args.len() != 3 {
            return Err("mixed_blocks --check RAW PACKED".into());
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
        return Err("mixed_blocks CORPUS STREAMS ROUNDS MIN_MS METHOD".into());
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
