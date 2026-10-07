//! Research CLI, outside the codec/model boundary.
use structured_codec::{DictionaryMode, Settings};

fn run() -> Result<(), String> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.first().is_some_and(|a| a == "decode") && args.len() == 4 {
        let packet = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let limit = args[3].parse().map_err(|_| "invalid limit")?;
        let raw = structured_codec::decode_with_limit(&packet, limit).map_err(|e| e.category())?;
        return std::fs::write(&args[2], raw).map_err(|e| e.to_string());
    }
    if args.first().is_some_and(|a| a == "encode" || a == "plain") && args.len() == 6 {
        let raw = std::fs::read(&args[1]).map_err(|e| e.to_string())?;
        let settings = Settings {
            chunk_log2: args[3].parse().map_err(|_| "invalid chunk log2")?,
            dictionary: match args[4].as_str() {
                "off" => DictionaryMode::Off,
                "keys" => DictionaryMode::Keys,
                "all-quoted" => DictionaryMode::AllQuoted,
                _ => return Err("invalid dictionary mode".into()),
            },
            numbers: match args[5].as_str() {
                "off" => false,
                "checked-delta" => true,
                _ => return Err("invalid numeric mode".into()),
            },
        };
        let packet = if args[0] == "plain" {
            structured_codec::encode_untransformed(&raw, settings)
        } else {
            structured_codec::encode(&raw, settings)
        }
        .map_err(|e| e.category())?;
        return std::fs::write(&args[2], packet).map_err(|e| e.to_string());
    }
    Err(
        "structured-tool decode INPUT OUTPUT LIMIT | encode|plain INPUT OUTPUT LOG2 DICT NUMBERS"
            .into(),
    )
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
