#[allow(dead_code)]
mod adapter {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../new-methods-bench/src/bin/structured_worker.rs"
    ));
    pub fn factory(level: &str, frame: &str) -> Result<Box<dyn Engine>> {
        if !matches!(frame, "frame" | "plain") {
            return Err("invalid DSC1 framing".into());
        }
        let fields: Vec<_> = level.split('/').collect();
        if fields.len() != 3 {
            return Err("DSC1 level LOG2/DICT/NUMBERS".into());
        }
        let chunk_log2 = fields[0].parse().map_err(|_| "chunk log2")?;
        if ![16, 18].contains(&chunk_log2) {
            return Err("chunk outside roster".into());
        }
        let dictionary = match fields[1] {
            "off" => DictionaryMode::Off,
            "keys" => DictionaryMode::Keys,
            "all-quoted" => DictionaryMode::AllQuoted,
            _ => return Err("dictionary outside roster".into()),
        };
        let numbers = match fields[2] {
            "off" => false,
            "checked-delta" => true,
            _ => return Err("numbers outside roster".into()),
        };
        if frame == "plain" && (dictionary != DictionaryMode::Off || numbers) {
            return Err("plain uses LOG2/off/off".into());
        }
        Ok(Box::new(Structured {
            settings: Settings {
                chunk_log2,
                dictionary,
                numbers,
            },
            plain: frame == "plain",
        }))
    }
}
fn main() {
    new_methods_decode::run("dsc1", adapter::factory);
}
