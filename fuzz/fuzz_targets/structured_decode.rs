#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|packet: &[u8]| {
    // Wire stream budgets are checked in addition to this output ceiling.
    let _ = structured_codec::decode_with_limit(packet, 1 << 20);
});
