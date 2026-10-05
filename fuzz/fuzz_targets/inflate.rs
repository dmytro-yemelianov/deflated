#![no_main]
use libfuzzer_sys::fuzz_target;

// Every crash or hang on malformed input is a bug (spec §12). The limit keeps
// the fuzzer from reporting OOM on a legitimate bomb, which is correct
// behavior, not a defect.
fuzz_target!(|data: &[u8]| {
    let _ = deflate_core::inflate_with_limit(data, 1 << 20);
});
