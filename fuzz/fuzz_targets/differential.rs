#![no_main]
use libfuzzer_sys::fuzz_target;

// Agreement with an independent decoder, in-process, at fuzzing throughput.
// Only successes are compared: the two disagree legitimately about *which*
// error a malformed stream earns, and about incomplete trees unless both
// follow ADR 0004. A success/success pair with different bytes is always a
// bug in one of them.
fuzz_target!(|data: &[u8]| {
    let ours = deflate_core::inflate_with_limit(data, 1 << 20);
    let theirs = miniz_oxide::inflate::decompress_to_vec(data);
    if let (Ok(a), Ok(b)) = (&ours, &theirs) {
        assert_eq!(a, b, "decoders disagree on a stream both accepted");
    }
});
