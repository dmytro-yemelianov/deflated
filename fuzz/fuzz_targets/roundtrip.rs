#![no_main]
use libfuzzer_sys::fuzz_target;

// The compressor must produce a stream the decoder maps back to the input.
fuzz_target!(|data: &[u8]| {
    let level = match data.first().copied().unwrap_or(0) % 3 {
        0 => deflate_core::CompressionLevel::Fast,
        1 => deflate_core::CompressionLevel::Balanced,
        _ => deflate_core::CompressionLevel::Best,
    };
    let packed = deflate_core::deflate_with_level(data, level);
    let back = deflate_core::inflate(&packed).expect("own output must decode");
    assert_eq!(back, data);
});
