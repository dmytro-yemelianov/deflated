use new_methods_bench::{
    Result,
    worker::{self, Engine},
};
use structured_codec::{DictionaryMode, Settings};

struct Structured {
    settings: Settings,
    plain: bool,
}
impl Engine for Structured {
    fn encode(&self, raw: &[u8]) -> Result<Vec<u8>> {
        let encode = if self.plain {
            structured_codec::encode_untransformed
        } else {
            structured_codec::encode
        };
        encode(raw, self.settings).map_err(|e| format!("DSC1 {e:?}"))
    }
    fn decode(&self, packet: &[u8], expected: usize) -> Result<Vec<u8>> {
        let out = structured_codec::decode_with_limit(packet, expected)
            .map_err(|e| format!("DSC1 {e:?}"))?;
        if out.len() != expected {
            return Err("DSC1 output size".into());
        }
        Ok(out)
    }
}
fn main() {
    worker::run(
        "dsc1",
        "{\"codec\":\"DSC1-experimental\",\"version\":1,\"backend\":\"requires b7 core source hash gate\"}",
        |level, frame| {
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
        },
    );
}
