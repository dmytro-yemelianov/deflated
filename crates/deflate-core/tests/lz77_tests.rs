use deflate_core::Error;
use deflate_core::bitstream::BitReader;
use deflate_core::lz77::{DIST_BASE, LENGTH_BASE, copy_back, read_distance, read_length};

#[test]
fn non_overlapping_copy() {
    let mut out = b"abcdef".to_vec();
    copy_back(&mut out, 6, 3).unwrap();
    assert_eq!(out, b"abcdefabc");
}

#[test]
fn overlapping_copy_repeats_the_source() {
    // dist 1, len 5: the byte is repeated, not read five times from one place.
    let mut out = b"xa".to_vec();
    copy_back(&mut out, 1, 5).unwrap();
    assert_eq!(out, b"xaaaaaa");
}

#[test]
fn overlapping_copy_with_period_three() {
    let mut out = b"abc".to_vec();
    copy_back(&mut out, 3, 7).unwrap();
    assert_eq!(out, b"abcabcabca");
}

#[test]
fn maximum_length_copy() {
    let mut out = vec![b'q'];
    copy_back(&mut out, 1, 258).unwrap();
    assert_eq!(out.len(), 259);
    assert!(out.iter().all(|&b| b == b'q'));
}

// --- Review Focus 4: the output boundary ---

#[test]
fn distance_equal_to_output_length_is_legal() {
    // The very first byte produced is exactly `out.len()` back.
    let mut out = b"abc".to_vec();
    copy_back(&mut out, 3, 1).unwrap();
    assert_eq!(out, b"abca");
}

#[test]
fn distance_one_past_the_output_is_rejected() {
    let mut out = b"abc".to_vec();
    assert_eq!(copy_back(&mut out, 4, 1), Err(Error::InvalidDistance));
    assert_eq!(out, b"abc", "a rejected copy must not modify the output");
}

#[test]
fn zero_distance_is_rejected() {
    let mut out = b"abc".to_vec();
    assert_eq!(copy_back(&mut out, 0, 1), Err(Error::InvalidDistance));
    assert_eq!(out, b"abc");
}

#[test]
fn any_distance_into_empty_output_is_rejected() {
    let mut out = Vec::new();
    for d in [0usize, 1, 2, 32768, usize::MAX] {
        assert_eq!(copy_back(&mut out, d, 1), Err(Error::InvalidDistance));
    }
    assert!(out.is_empty());
}

// --- symbol tables ---

#[test]
fn length_symbols_span_three_to_258() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(257, &mut r).unwrap(), 3);
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(285, &mut r).unwrap(), 258);
    // 284 with all five extra bits set also reaches 258 — legal, if unusual.
    let data = [0xFFu8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(284, &mut r).unwrap(), 258);
}

#[test]
fn length_symbols_outside_the_range_are_rejected() {
    let data = [0u8; 4];
    for s in [0u16, 256, 286, 287, 300] {
        let mut r = BitReader::new(&data);
        assert_eq!(read_length(s, &mut r), Err(Error::InvalidLength));
    }
}

#[test]
fn distance_symbols_span_one_to_32768() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_distance(0, &mut r).unwrap(), 1);
    let data = [0xFFu8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_distance(29, &mut r).unwrap(), 24577 + 8191);
}

#[test]
fn distance_symbols_thirty_and_thirty_one_are_rejected() {
    let data = [0u8; 4];
    for s in [30u16, 31, 99] {
        let mut r = BitReader::new(&data);
        assert_eq!(read_distance(s, &mut r), Err(Error::InvalidDistance));
    }
}

#[test]
fn tables_have_the_sizes_rfc_1951_requires() {
    assert_eq!(LENGTH_BASE.len(), 29); // symbols 257..=285
    assert_eq!(DIST_BASE.len(), 30); // symbols 0..=29
}

#[test]
fn truncated_extra_bits_are_eof() {
    let mut r = BitReader::new(&[]);
    assert_eq!(read_length(269, &mut r), Err(Error::UnexpectedEof)); // needs 2 extra bits
    let mut r = BitReader::new(&[]);
    assert_eq!(read_distance(29, &mut r), Err(Error::UnexpectedEof)); // needs 13
}

// --- copy_back against a byte-at-a-time reference ---

/// The RFC 1951 §3.2.3 copy, written the obvious way, as the oracle for
/// whatever bulk strategy `copy_back` uses.
fn reference_copy_back(out: &mut Vec<u8>, dist: usize, len: usize) -> Result<(), Error> {
    if dist == 0 || dist > out.len() {
        return Err(Error::InvalidDistance);
    }
    for _ in 0..len {
        let b = out[out.len() - dist];
        out.push(b);
    }
    Ok(())
}

#[test]
fn copy_back_matches_byte_at_a_time_reference() {
    for prefix_len in 1..=40usize {
        // Distinct bytes make any misplaced source byte visible.
        let prefix: Vec<u8> = (0..prefix_len)
            .map(|i| (i as u8).wrapping_mul(37).wrapping_add(prefix_len as u8))
            .collect();
        for dist in 0..=prefix_len + 2 {
            for len in 0..=300usize {
                let mut want = prefix.clone();
                let want_res = reference_copy_back(&mut want, dist, len);
                let mut got = prefix.clone();
                let got_res = copy_back(&mut got, dist, len);
                assert_eq!(
                    got_res, want_res,
                    "prefix {prefix_len} dist {dist} len {len}"
                );
                assert_eq!(got, want, "prefix {prefix_len} dist {dist} len {len}");
            }
        }
    }
}

#[test]
fn copy_back_rejects_huge_distance_and_leaves_output_alone() {
    let mut out = b"abc".to_vec();
    assert_eq!(
        copy_back(&mut out, usize::MAX, 5),
        Err(Error::InvalidDistance)
    );
    assert_eq!(out, b"abc");
    let mut empty = Vec::new();
    assert_eq!(copy_back(&mut empty, 1, 0), Err(Error::InvalidDistance));
    assert!(empty.is_empty());
}
