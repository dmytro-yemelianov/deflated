use deflate_core::crc32::Crc32;

fn bit_reference(data: &[u8]) -> u32 {
    let mut crc = u32::MAX;
    for &byte in data {
        crc ^= u32::from(byte);
        for _ in 0..8 {
            crc = (crc >> 1) ^ if crc & 1 != 0 { 0xedb88320 } else { 0 };
        }
    }
    !crc
}

#[test]
fn slicing_matches_bit_reference_at_unaligned_tails_and_chunk_boundaries() {
    let data: Vec<u8> = (0..4200)
        .map(|i: u32| (i.wrapping_mul(37) ^ (i >> 3)) as u8)
        .collect();
    for offset in 0..16 {
        for len in (0..40).chain([63, 64, 65, 255, 256, 257, 4095, 4096, 4097]) {
            let input = &data[offset..offset + len];
            let expected = bit_reference(input);
            assert_eq!(Crc32::compute(input), expected);
            for chunk_size in [1, 3, 7, 8, 9, 16, 31, 64] {
                let mut crc = Crc32::new();
                for chunk in input.chunks(chunk_size) {
                    crc.update(chunk);
                    crc.update(&[]);
                }
                assert_eq!(
                    crc.finalize(),
                    expected,
                    "offset={offset}, len={len}, chunk={chunk_size}"
                );
            }
        }
    }
}
