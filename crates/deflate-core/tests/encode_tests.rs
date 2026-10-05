use deflate_core::{MAX_STORED, deflate_stored, inflate};

#[test]
fn roundtrips_through_our_own_decoder() {
    for raw in [
        b"".to_vec(),
        b"a".to_vec(),
        b"hello world".to_vec(),
        vec![0u8; 1000],
        (0..=255u8).collect::<Vec<_>>(),
    ] {
        assert_eq!(
            inflate(&deflate_stored(&raw)).unwrap(),
            raw,
            "len {}",
            raw.len()
        );
    }
}

#[test]
fn roundtrips_through_zlib() {
    // P10: the output must be valid RFC 1951, which means a decoder that is
    // not ours accepts it. Our own decoder agreeing proves only that the two
    // halves share a misunderstanding (spec §2).
    for raw in [b"".to_vec(), b"hi".to_vec(), vec![7u8; 5000]] {
        let s = deflate_stored(&raw);
        let back = miniz_oxide::inflate::decompress_to_vec(&s)
            .expect("an independent decoder must accept our output");
        assert_eq!(back, raw);
    }
}

#[test]
fn chunks_at_the_stored_block_boundary() {
    for n in [
        MAX_STORED - 1,
        MAX_STORED,
        MAX_STORED + 1,
        MAX_STORED * 2,
        MAX_STORED * 2 + 1,
    ] {
        let raw: Vec<u8> = (0..n).map(|i| (i % 251) as u8).collect();
        let s = deflate_stored(&raw);
        assert_eq!(inflate(&s).unwrap(), raw, "n = {n}");
        let back = miniz_oxide::inflate::decompress_to_vec(&s).expect("valid at n = {n}");
        assert_eq!(back, raw);
    }
}

#[test]
fn empty_input_yields_one_final_empty_block() {
    // A stream with no blocks is not valid DEFLATE.
    assert_eq!(deflate_stored(b""), vec![0x01, 0x00, 0x00, 0xFF, 0xFF]);
    assert_eq!(inflate(&deflate_stored(b"")).unwrap(), b"");
}

#[test]
fn output_is_bounded_by_input_plus_framing() {
    for n in [0usize, 1, MAX_STORED, MAX_STORED * 3] {
        let raw = vec![0u8; n];
        let s = deflate_stored(&raw);
        let blocks = n.div_ceil(MAX_STORED).max(1);
        assert_eq!(s.len(), n + 5 * blocks, "n = {n}");
    }
}
