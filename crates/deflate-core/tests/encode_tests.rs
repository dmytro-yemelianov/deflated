use deflate_core::bitstream::BitReader;
use deflate_core::bitwriter::BitWriter;
use deflate_core::error::Error;
use deflate_core::huffman::fixed_litlen;
use deflate_core::tokens::{Token, expand};
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

fn xorshift(state: &mut u64) -> u64 {
    *state ^= *state << 13;
    *state ^= *state >> 7;
    *state ^= *state << 17;
    *state
}

#[test]
fn write_bits_roundtrips_every_width_and_offset() {
    let mut rng = 0x9E37_79B9_7F4A_7C15u64;
    for n in 0..=32u32 {
        for offset in 0..=7u32 {
            for _ in 0..20 {
                let v = (xorshift(&mut rng) as u32) & if n == 32 { u32::MAX } else { (1 << n) - 1 };
                let pre = (xorshift(&mut rng) as u32) & ((1 << offset) - 1);
                let post = xorshift(&mut rng) as u32;
                let mut w = BitWriter::new();
                w.write_bits(pre, offset);
                w.write_bits(v, n);
                w.write_bits(post, 13);
                assert_eq!(w.bit_len(), (offset + n + 13) as usize);
                let bytes = w.finish();
                let mut r = BitReader::new(&bytes);
                assert_eq!(r.read_bits(offset).unwrap(), pre);
                assert_eq!(r.read_bits(n).unwrap(), v, "n {n} offset {offset}");
                assert_eq!(r.read_bits(13).unwrap(), post & 0x1FFF);
            }
        }
    }
}

#[test]
fn write_bits_masks_high_bits_and_finish_pads_with_zeros() {
    let mut w = BitWriter::new();
    w.write_bits(0xFF, 3);
    assert_eq!(w.bit_len(), 3);
    assert_eq!(w.finish(), vec![0b0000_0111]);
    assert_eq!(BitWriter::new().finish(), Vec::<u8>::new());
}

fn fixed_code(sym: u32) -> (u32, u32) {
    match sym {
        0..=143 => (0x30 + sym, 8),
        144..=255 => (0x190 + sym - 144, 9),
        256..=279 => (sym - 256, 7),
        _ => (0xC0 + sym - 280, 8),
    }
}

#[test]
fn write_code_matches_fixed_table() {
    let table = fixed_litlen();
    for sym in 0..288u32 {
        let (code, len) = fixed_code(sym);
        let mut w = BitWriter::new();
        w.write_bits(0b101, 3);
        w.write_code(code, len);
        assert_eq!(w.bit_len(), 3 + len as usize);
        let bytes = w.finish();
        let mut r = BitReader::new(&bytes);
        assert_eq!(r.read_bits(3).unwrap(), 0b101);
        assert_eq!(table.decode(&mut r).unwrap(), sym as u16, "sym {sym}");
    }
}

#[test]
fn expand_literals_and_matches() {
    let toks = [
        Token::Literal(b'a'),
        Token::Literal(b'b'),
        Token::Match { len: 4, dist: 2 },
        Token::Match { len: 3, dist: 6 },
    ];
    assert_eq!(expand(&toks).unwrap(), b"ababababa");
    assert_eq!(
        expand(&[Token::Literal(7), Token::Match { len: 258, dist: 1 }]).unwrap(),
        vec![7u8; 259]
    );
    assert_eq!(expand(&[]).unwrap(), Vec::<u8>::new());
}

#[test]
fn expand_rejects_distance_before_start() {
    assert_eq!(
        expand(&[Token::Literal(1), Token::Match { len: 3, dist: 2 }]),
        Err(Error::InvalidDistance)
    );
    assert_eq!(
        expand(&[Token::Match { len: 3, dist: 1 }]),
        Err(Error::InvalidDistance)
    );
}
