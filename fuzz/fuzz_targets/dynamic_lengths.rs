#![no_main]
use deflate_core::huffman_build::build_lengths;
use libfuzzer_sys::fuzz_target;

// `build_lengths` must give a length set the decoder accepts for any
// frequency vector: Kraft-valid, nonzero exactly where the frequency is.
fuzz_target!(|data: &[u8]| {
    let freqs: Vec<u32> = data
        .chunks_exact(4)
        .take(286)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    for max_len in [7u8, 15] {
        let ls = build_lengths(&freqs, max_len);
        assert_eq!(ls.len(), freqs.len());
        let n = freqs.iter().filter(|&&f| f > 0).count();
        if n > 1usize << max_len {
            // No code exists; documented as all zeros.
            assert!(ls.iter().all(|&l| l == 0));
            continue;
        }
        assert!(ls.iter().all(|&l| l <= max_len));
        for (f, l) in freqs.iter().zip(&ls) {
            assert!(*f == 0 || *l != 0, "used symbol without a code");
        }
        let used = ls.iter().filter(|&&l| l != 0).count();
        let kraft: u64 = ls
            .iter()
            .filter(|&&l| l != 0)
            .map(|&l| 1u64 << (15 - l))
            .sum();
        // Complete, or a lone symbol, or empty.
        assert!(kraft == 1 << 15 || used <= 1, "kraft {kraft} used {used}");
    }
});
