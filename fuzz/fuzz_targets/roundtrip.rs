#![no_main]
use libfuzzer_sys::fuzz_target;

// The compressor must produce a stream the decoder maps back to the input.
fuzz_target!(|data: &[u8]| {
    let byte = |i| data.get(i).copied().unwrap_or(0);
    let packed = match byte(0) % 4 {
        0 => deflate_core::deflate_with_level(data, deflate_core::CompressionLevel::Fast),
        1 => deflate_core::deflate_with_level(data, deflate_core::CompressionLevel::Balanced),
        2 => deflate_core::deflate_with_level(data, deflate_core::CompressionLevel::Best),
        _ => {
            use deflate_core::research::{Config, Index};
            let probes = usize::from(u16::from_le_bytes([byte(1), byte(2)]) & 1023) + 1;
            let index = if byte(3) & 1 == 0 {
                Index::Dual
            } else {
                Index::Trigram
            };
            let config = Config::new(
                probes,
                byte(3) & 2 != 0,
                usize::from(byte(4) % 33),
                index,
                [256, 1024, 4096, 16384][usize::from(byte(5) % 4)],
            )
            .unwrap();
            deflate_core::research::deflate(data, config)
        }
    };
    let back = deflate_core::inflate(&packed).expect("own output must decode");
    assert_eq!(back, data);
    assert_eq!(
        miniz_oxide::inflate::decompress_to_vec(&packed).unwrap(),
        data
    );
});
