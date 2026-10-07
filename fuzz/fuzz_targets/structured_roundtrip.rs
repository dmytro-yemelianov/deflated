#![no_main]
use libfuzzer_sys::fuzz_target;
use structured_codec::{DictionaryMode, Settings};

fuzz_target!(|data: &[u8]| {
    if data.len() > 70000 {
        return;
    }
    let choice = data.first().copied().unwrap_or(0);
    let settings = Settings {
        chunk_log2: if choice & 1 == 0 { 16 } else { 18 },
        dictionary: match (choice / 2) % 3 {
            0 => DictionaryMode::Off,
            1 => DictionaryMode::Keys,
            _ => DictionaryMode::AllQuoted,
        },
        numbers: choice & 8 != 0,
    };
    let packet = structured_codec::encode(data, settings).unwrap();
    assert_eq!(
        structured_codec::decode_with_limit(&packet, data.len()).unwrap(),
        data
    );
    let plain = structured_codec::encode_untransformed(data, settings).unwrap();
    assert!(packet.len() <= plain.len());
});
