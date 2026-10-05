#![no_main]
use deflate_core::bitstream::BitReader;
use deflate_core::block::read_dynamic_tables;
use libfuzzer_sys::fuzz_target;

// The dynamic-tree parser is the most intricate parser in the format and the
// one most worth fuzzing in isolation: reaching it through `inflate` wastes
// most of the fuzzer's budget on block headers.
fuzz_target!(|data: &[u8]| {
    let mut r = BitReader::new(data);
    let _ = read_dynamic_tables(&mut r);
});
