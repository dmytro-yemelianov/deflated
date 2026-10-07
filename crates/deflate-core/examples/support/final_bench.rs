//! S9 measurement paths. All methods include fresh per-call encoder allocations.
use deflate_core::research::{Config, Index};
use std::hint::black_box;
use std::time::{Duration, Instant};
#[path = "adaptive.rs"]
mod adaptive;
#[path = "bounded_parse.rs"]
mod bounded_parse;
#[path = "policy.rs"]
mod policy;
#[path = "streaming_blocks.rs"]
mod streaming_blocks;
#[derive(Clone, Copy)]
pub(crate) enum BaseMethod {
    Preset(deflate_core::CompressionLevel),
    Stored,
    Configured(Config),
    Reference(u8),
    Bounded(bounded_parse::Settings),
    Adaptive(adaptive::Settings),
    Streaming(streaming_blocks::Settings),
}

impl BaseMethod {
    fn parse(text: &str) -> Result<Self, String> {
        use deflate_core::CompressionLevel;
        if text.starts_with("stream:") {
            return streaming_blocks::Settings::parse(text).map(Self::Streaming);
        }
        if text.starts_with("adaptive:") || text.starts_with("adaptive-entropy:") {
            return adaptive::Settings::parse(text).map(Self::Adaptive);
        }
        if text.starts_with("bounded:") {
            return bounded_parse::Settings::parse(text).map(Self::Bounded);
        }
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
            Self::Bounded(settings) => bounded_parse::encode::<false>(raw, settings).packet,
            Self::Adaptive(settings) => adaptive::encode(raw, settings),
            Self::Streaming(settings) => streaming_blocks::encode::<false>(raw, settings).packet,
        }
    }
}

enum Method {
    Base(BaseMethod),
    Policy(policy::Policy, policy::Execution),
}
impl Method {
    fn parse(text: &str) -> Result<Self, String> {
        for (prefix, execution) in [
            ("policy@", policy::Execution::Feature),
            ("policy-local@", policy::Execution::Regional),
            ("policy-exact@", policy::Execution::Exact),
        ] {
            if let Some(path) = text.strip_prefix(prefix) {
                return policy::Policy::load(path).map(|p| Self::Policy(p, execution));
            }
        }
        BaseMethod::parse(text).map(Self::Base)
    }
    fn encode(&self, raw: &[u8]) -> Vec<u8> {
        match self {
            Self::Base(method) => method.encode(raw),
            Self::Policy(selector, execution) => selector.encode(raw, *execution),
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
    if args.first().is_some_and(|a| a == "--selector-features") {
        if args.len() != 2 {
            return Err("final_bench --selector-features INPUT".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        println!("{:?}", policy::enhanced_features(&raw));
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--selector-inspect") {
        if args.len() != 4 {
            return Err("final_bench --selector-inspect INPUT OUT METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let method = Method::parse(&args[3])?;
        let packet = method.encode(&raw);
        let baseline = deflate_core::deflate(&raw);
        for data in [&packet, &baseline] {
            assert_eq!(deflate_core::inflate(data).unwrap(), raw);
            assert_eq!(miniz_oxide::inflate::decompress_to_vec(data).unwrap(), raw);
        }
        if args[3].starts_with("policy-exact@") {
            assert!((packet.len() as u128) * 100 <= (baseline.len() as u128) * 101);
        }
        write_packets(&args[2], &packet, Some(&baseline))?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"baseline_bytes\":{},\"features\":{:?},\"exact_cap\":{}}}",
            raw.len(),
            packet.len(),
            baseline.len(),
            policy::enhanced_features(&raw),
            args[3].starts_with("policy-exact@")
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--stream-inspect") {
        if args.len() != 4 {
            return Err("final_bench --stream-inspect INPUT OUT METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let settings = streaming_blocks::Settings::parse(&args[3])?;
        let output = streaming_blocks::encode::<true>(&raw, settings);
        assert_eq!(deflate_core::inflate(&output.packet).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&output.packet).unwrap(),
            raw
        );
        assert_eq!(
            output.packet,
            streaming_blocks::encode::<false>(&raw, settings).packet
        );
        write_packets(&args[2], &output.packet, None)?;
        let s = output.stats;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"blocks\":{},\"stored_blocks\":{},\"dynamic_blocks\":{},\"adaptive_boundaries\":{},\"maximum_buffer_tokens\":{},\"cross_block_matches\":{},\"matches_after_stored\":{},\"huffman_analyses\":{},\"stream_bits_before_fallback\":{},\"whole_stored_fallback\":{}}}",
            raw.len(),
            output.packet.len(),
            s.blocks,
            s.stored_blocks,
            s.dynamic_blocks,
            s.adaptive_boundaries,
            s.maximum_buffer_tokens,
            s.cross_block_matches,
            s.matches_after_stored,
            s.huffman_analyses,
            s.attempted_stream_bits,
            s.whole_stored_fallback
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--adaptive-inspect") {
        if args.len() != 4 {
            return Err("final_bench --adaptive-inspect INPUT OUT METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let settings = adaptive::Settings::parse(&args[3])?;
        let hint = adaptive::hint(&raw, settings.samples, settings.entropy_guard);
        let regional = deflate_core::research::deflate_adaptive(&raw, settings.regional);
        let baseline = deflate_core::deflate(&raw);
        let packet = adaptive::encode(&raw, settings);
        for data in [&regional, &baseline, &packet] {
            assert_eq!(deflate_core::inflate(data).unwrap(), raw);
            assert_eq!(miniz_oxide::inflate::decompress_to_vec(data).unwrap(), raw);
        }
        write_packets(&args[2], &packet, Some(&baseline))?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"baseline_bytes\":{},\"regional_bytes\":{},\"samples\":{},\"sample_repeats\":{},\"stored_prediction\":{},\"exact_cap_percent\":{},\"used_symbols\":{},\"peak_count\":{},\"entropy_guard\":{}}}",
            raw.len(),
            packet.len(),
            baseline.len(),
            regional.len(),
            hint.samples,
            hint.repeats,
            hint.stored,
            settings.exact_cap_percent,
            hint.used_symbols,
            hint.peak_count,
            settings.entropy_guard
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--bounded-inspect") {
        if args.len() != 4 {
            return Err("final_bench --bounded-inspect INPUT OUT METHOD".into());
        }
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let settings = bounded_parse::Settings::parse(&args[3])?;
        let output = bounded_parse::encode::<true>(&raw, settings);
        assert_eq!(deflate_core::inflate(&output.packet).unwrap(), raw);
        assert_eq!(
            miniz_oxide::inflate::decompress_to_vec(&output.packet).unwrap(),
            raw
        );
        write_packets(&args[2], &output.packet, None)?;
        let s = output.stats;
        let mut fixed_bits = None;
        if raw.len() <= 4096 {
            use deflate_core::tokens::Token;
            let tokens = bounded_parse::short_tokens(&raw, settings)?;
            assert_eq!(deflate_core::tokens::expand(&tokens).unwrap(), raw);
            let mut writer = deflate_core::bitwriter::BitWriter::new();
            deflate_core::encode_fixed::emit_fixed_block(&mut writer, true, tokens.iter().copied());
            fixed_bits = Some(writer.bit_len());
            let json = tokens
                .iter()
                .map(|token| match token {
                    Token::Literal(b) => format!("{{\"lit\":{b}}}"),
                    Token::Match { len, dist } => format!("{{\"len\":{len},\"dist\":{dist}}}"),
                })
                .collect::<Vec<_>>()
                .join(",");
            std::fs::write(
                std::path::Path::new(&args[2]).join("tokens.json"),
                format!("[{json}]\n"),
            )
            .map_err(|e| e.to_string())?;
            std::fs::write(
                std::path::Path::new(&args[2]).join("fixed.deflate"),
                writer.finish(),
            )
            .map_err(|e| e.to_string())?;
        }
        let fixed_json = fixed_bits.map_or_else(|| "null".to_string(), |n| n.to_string());
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"fixed_bits\":{fixed_json},\"candidate_visits\":{},\"comparison_bytes_examined\":{},\"insertions\":{},\"lookahead_queries\":{},\"rejected_unprofitable\":{},\"tokens\":{},\"blocks\":{},\"huffman_analyses\":{},\"refinement_blocks_kept\":{},\"estimated_payload_bits\":{},\"actual_payload_bits\":{},\"header_and_eob_bits\":{},\"attempted_stream_bits\":{},\"stored_selected\":{}}}",
            raw.len(),
            output.packet.len(),
            s.candidate_visits,
            s.comparison_bytes_examined,
            s.insertions,
            s.lookahead_queries,
            s.rejected_unprofitable,
            s.tokens,
            s.blocks,
            s.huffman_analyses,
            s.refinement_blocks_kept,
            s.estimated_payload_bits,
            s.actual_payload_bits,
            s.header_and_eob_bits,
            s.attempted_stream_bits,
            s.stored_selected
        );
        return Ok(());
    }
    if args.first().is_some_and(|a| a == "--memory") {
        if args.len() != 4 {
            return Err("final_bench --memory INPUT OUTPUT METHOD".into());
        }
        return memory(&args[3], &args[1], &args[2]);
    }
    if args.len() != 6 {
        return Err("final_bench warm|cold|profile INPUT OUT MIN_MS METHOD ORDER".into());
    }
    if !["warm", "cold", "profile"].contains(&args[0].as_str()) {
        return Err("invalid workload".into());
    }
    let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
    let method = Method::parse(&args[4])?;
    let min_ms: u64 = args[3].parse().map_err(|_| "invalid batch")?;
    let order: usize = args[5].parse().map_err(|_| "invalid order")?;
    if min_ms == 0 || order > 1 {
        return Err("invalid batch or order".into());
    }
    if args[0] == "profile" {
        // Sampling-only workload: disk/policy parsing precede the loop and
        // no decoder/oracle runs contaminate the encoder samples. The driver
        // validates the emitted packet separately. This is not a benchmark.
        let packet = method.encode(black_box(&raw));
        let start = Instant::now();
        let mut iterations = 0_u64;
        while start.elapsed() < Duration::from_millis(min_ms) {
            black_box(method.encode(black_box(&raw)));
            iterations += 1;
        }
        write_packets(&args[2], &packet, None)?;
        println!(
            "{{\"raw_bytes\":{},\"packed_bytes\":{},\"profile_iterations\":{iterations}}}",
            raw.len(),
            packet.len()
        );
        return Ok(());
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
