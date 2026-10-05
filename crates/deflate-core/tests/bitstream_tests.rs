use deflate_core::Error;
use deflate_core::bitstream::BitReader;

#[test]
fn reads_bits_least_significant_first() {
    // 0b1011_0010 = 0xB2. LSB-first the bits are 0,1,0,0,1,1,0,1.
    let data = [0xB2u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn read_bits_packs_first_bit_as_lsb() {
    // Low three bits of 0xB2 are 0b010 = 2 when read LSB-first.
    let data = [0xB2u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(3).unwrap(), 0b010);
    assert_eq!(r.bit_pos(), 3);
}

#[test]
fn read_bits_spans_byte_boundaries() {
    // 0x01,0x02 -> bits LSB-first: 1,0,0,0,0,0,0,0 | 0,1,0,0,0,0,0,0
    // Sixteen bits read at once is little-endian: 0x0201.
    let data = [0x01u8, 0x02];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(16).unwrap(), 0x0201);
}

#[test]
fn read_bits_zero_is_always_ok_even_at_eof() {
    let mut r = BitReader::new(&[]);
    assert_eq!(r.read_bits(0).unwrap(), 0);
    assert_eq!(r.bit_pos(), 0);
}

// --- Review Focus 1: truncation at every boundary, bit layer ---

#[test]
fn empty_input_reports_eof_not_panic() {
    let mut r = BitReader::new(&[]);
    assert_eq!(r.read_bit(), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0);
}

#[test]
fn short_read_is_atomic_and_leaves_position_untouched() {
    // Nine bits requested, eight available. The spec's P1 requires that a
    // failed read leave unrelated input unchanged.
    let data = [0xFFu8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(9), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0, "a failed read must not consume bits");
    // The reader is still usable.
    assert_eq!(r.read_bits(8).unwrap(), 0xFF);
}

#[test]
fn reading_past_the_end_keeps_reporting_eof() {
    let data = [0x00u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(8).unwrap(), 0);
    for _ in 0..4 {
        assert_eq!(r.read_bit(), Err(Error::UnexpectedEof));
    }
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn oversized_request_is_rejected_without_panicking() {
    let data = [0xFFu8; 8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(33), Err(Error::InvalidCode));
    assert_eq!(r.bit_pos(), 0);
}

// --- alignment ---

#[test]
fn align_to_byte_is_a_noop_when_already_aligned() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 0);
    let _ = r.read_bits(8).unwrap();
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn align_to_byte_rounds_up_and_is_idempotent() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    let _ = r.read_bits(3).unwrap();
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn aligned_u16_is_little_endian() {
    let data = [0x34u8, 0x12];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_aligned_u16_le().unwrap(), 0x1234);
    assert_eq!(r.bit_pos(), 16);
}

#[test]
fn aligned_u16_short_is_eof_and_atomic() {
    let data = [0x34u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_aligned_u16_le(), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0);
}

/// Reference: `n` bits assembled from `read_bit` on a throwaway reader, as
/// Lean `readBits` does. Errors on the first short `read_bit`; the caller's
/// reader is never touched, so atomicity is checked separately via `bit_pos`.
fn reference_read_bits(data: &[u8], pos: usize, n: u32) -> Result<u32, Error> {
    if n > 32 {
        return Err(Error::InvalidCode);
    }
    let mut r = BitReader::new(data);
    for _ in 0..pos {
        r.read_bit().unwrap();
    }
    let mut v: u32 = 0;
    for k in 0..n {
        v |= r.read_bit()? << k;
    }
    Ok(v)
}

#[test]
fn read_bits_matches_bit_by_bit_reference_everywhere() {
    // Deterministic buffers of every length 0..=9 with varied bit patterns.
    let mut seed: u32 = 0x9E37_79B9;
    for len in 0..=9usize {
        for pattern in 0..3 {
            let data: Vec<u8> = (0..len)
                .map(|i| match pattern {
                    0 => 0xFF,
                    1 => (i as u8).wrapping_mul(37) ^ 0xA5,
                    _ => {
                        seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                        (seed >> 24) as u8
                    }
                })
                .collect();
            for start in 0..=len * 8 {
                for n in 0..=33u32 {
                    let mut r = BitReader::new(&data);
                    for _ in 0..start {
                        r.read_bit().unwrap();
                    }
                    let got = r.read_bits(n);
                    let want = reference_read_bits(&data, start, n);
                    assert_eq!(got, want, "len={len} pattern={pattern} start={start} n={n}");
                    let expected_pos = if got.is_ok() {
                        start + n as usize
                    } else {
                        start
                    };
                    assert_eq!(r.bit_pos(), expected_pos, "len={len} start={start} n={n}");
                }
            }
        }
    }
}
