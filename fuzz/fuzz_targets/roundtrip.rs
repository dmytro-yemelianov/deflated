#![no_main]
use libfuzzer_sys::fuzz_target;

// The compressor must produce a stream the decoder maps back to the input.
fuzz_target!(|data: &[u8]| {
    let packed = deflate_core::deflate(data);
    let back = deflate_core::inflate(&packed).expect("own output must decode");
    assert_eq!(back, data);
});
