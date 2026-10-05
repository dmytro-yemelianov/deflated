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

// ---- Task 7: fixed-Huffman emitter ----
use deflate_core::encode_fixed::{dist_sym, emit_fixed, length_sym};
use deflate_core::lz77::{read_distance, read_length};

#[test]
fn length_and_dist_symbols_read_back() {
    for len in 3..=258u16 {
        let (sym, extra, nbits) = length_sym(len);
        let mut w = BitWriter::new();
        w.write_bits(extra, nbits);
        let bytes = w.finish();
        let mut r = BitReader::new(&bytes);
        assert_eq!(read_length(sym, &mut r).unwrap(), usize::from(len));
    }
    for dist in 1..=32768u32 {
        let (sym, extra, nbits) = dist_sym(dist as u16);
        let mut w = BitWriter::new();
        w.write_bits(extra, nbits);
        let bytes = w.finish();
        let mut r = BitReader::new(&bytes);
        assert_eq!(read_distance(sym, &mut r).unwrap(), dist as usize);
    }
}

fn check(ts: &[Token]) {
    let want = expand(ts).unwrap();
    assert_eq!(inflate(&emit_fixed(ts.iter().copied())).unwrap(), want);
}

#[test]
fn emit_fixed_empty_and_literals() {
    check(&[]);
    let all: Vec<Token> = (0..=255u8).map(Token::Literal).collect();
    check(&all);
}

#[test]
fn emit_fixed_match_bounds() {
    check(&[Token::Literal(7), Token::Match { len: 258, dist: 1 }]);
    // dist == out.len() (Review Focus 3)
    check(&[
        Token::Literal(1),
        Token::Literal(2),
        Token::Literal(3),
        Token::Match { len: 3, dist: 3 },
    ]);
    // dist 32768 after a 32768-byte prefix
    let mut ts: Vec<Token> = (0..32768u32)
        .map(|i| Token::Literal((i % 251) as u8))
        .collect();
    ts.push(Token::Match {
        len: 258,
        dist: 32768,
    });
    check(&ts);
    // overlapping dist < len
    check(&[
        Token::Literal(1),
        Token::Literal(2),
        Token::Match { len: 100, dist: 2 },
    ]);
}

mod matcher_tests {
    use deflate_core::matcher::{accept, tokens};
    use deflate_core::tokens::{Token, expand};

    fn check(x: &[u8]) -> Vec<Token> {
        let ts: Vec<Token> = tokens(x).collect();
        assert_eq!(expand(&ts).unwrap(), x);
        let mut i = 0;
        for t in &ts {
            match *t {
                Token::Literal(_) => i += 1,
                Token::Match { len, dist } => {
                    assert!(accept(x, i, len.into(), dist.into()), "at {i}");
                    i += usize::from(len);
                }
            }
        }
        assert_eq!(i, x.len());
        ts
    }

    #[test]
    fn small_inputs() {
        for n in 0..=3 {
            check(&b"aaa"[..n]);
        }
        check(b"abcabc");
    }

    #[test]
    fn random_64k() {
        let mut s = 0x1234_5678u32;
        let x: Vec<u8> = (0..65536)
            .map(|_| {
                s = s.wrapping_mul(1664525).wrapping_add(1013904223);
                (s >> 24) as u8
            })
            .collect();
        check(&x);
    }

    #[test]
    fn zeros_1mib_is_fast_and_long_matches() {
        let x = vec![0u8; 1 << 20];
        let t = std::time::Instant::now();
        let ts = check(&x);
        assert!(t.elapsed().as_secs() < 1);
        assert!(ts.contains(&Token::Match { len: 258, dist: 1 }));
    }

    #[test]
    fn repeats_and_text() {
        let abc: Vec<u8> = b"abc".iter().cycle().take(5000).copied().collect();
        check(&abc);
        let text = b"the quick brown fox jumps over the lazy dog. ".repeat(200);
        let ts = check(&text);
        assert!(ts.len() < text.len() / 5);
    }

    #[test]
    fn far_distance() {
        let mut x = b"xyzxyz!".to_vec();
        x.extend(std::iter::repeat_n(7u8, 32768 - 7));
        x.extend_from_slice(b"xyzxyz!");
        check(&x);
    }

    #[test]
    fn accept_rejects_each_bound() {
        let x = b"abcabcabcabc";
        assert!(accept(x, 3, 9, 3));
        assert!(!accept(x, 3, 2, 3)); // len < 3
        assert!(!accept(x, 3, 259, 3)); // len > 258
        assert!(!accept(x, 3, 3, 0)); // dist 0
        assert!(!accept(x, 3, 3, 4)); // dist > i
        assert!(!accept(x, 3, 10, 3)); // runs past end
        assert!(!accept(x, 4, 3, 2)); // mismatch
        let big = vec![0u8; 40000];
        assert!(accept(&big, 32768, 258, 32768));
        assert!(!accept(&big, 32769, 258, 32769)); // dist > 32768
        assert!(!accept(x, usize::MAX, 3, 1)); // overflow
    }
}

// ---- deflate (Lean `compress`, spec §3.6) ----
use deflate_core::deflate as compress;

fn rand_bytes(n: usize, seed: u64) -> Vec<u8> {
    let mut s = seed;
    (0..n).map(|_| xorshift(&mut s) as u8).collect()
}

fn stored_size(n: usize) -> usize {
    n + 5 * n.div_ceil(MAX_STORED).max(1)
}

fn rt(x: &[u8]) -> Vec<u8> {
    let d = compress(x);
    assert_eq!(inflate(&d).unwrap(), x, "len {}", x.len());
    assert!(d.len() <= stored_size(x.len()), "len {}", x.len());
    d
}

#[test]
fn deflate_empty() {
    rt(&[]);
}

#[test]
fn deflate_stored_chunk_boundaries() {
    for n in [65534usize, 65535, 65536, 65537, 131070, 131071, 131072] {
        let r = rand_bytes(n, 7);
        assert_eq!(rt(&r), deflate_stored(&r), "random {n}");
        rt(&vec![b'a'; n]);
    }
}

#[test]
fn deflate_match_bounds() {
    // len 258 at dist 1 and overlapping dist < len.
    rt(&vec![7u8; 300]);
    rt(&b"abc".repeat(200));
    // dist = i (match right at the start of the second copy).
    let p = rand_bytes(300, 3);
    rt(&[p.clone(), p.clone()].concat());
    // dist 32768 exactly, len 258.
    let p = rand_bytes(32768, 5);
    let mut x = p.clone();
    x.extend_from_slice(p.get(..258).unwrap());
    // Random prefix makes fixed lose to stored; round trip and bound still hold.
    rt(&x);
}

#[test]
fn deflate_long_runs() {
    let d = rt(&vec![0u8; 1 << 20]);
    assert!(d.len() < 1 << 14);
    rt(&b"xy".repeat(100_000));
}

#[test]
fn deflate_zeros_is_fast() {
    let t = std::time::Instant::now();
    compress(&vec![0u8; 1 << 20]);
    assert!(t.elapsed().as_secs_f64() < 1.0);
}

#[test]
fn deflate_random_is_stored() {
    for n in [1000usize, 70000] {
        let r = rand_bytes(n, 11);
        assert_eq!(compress(&r), deflate_stored(&r), "len {n}");
    }
}

#[test]
fn deflate_text_beats_stored() {
    let t = b"The quick brown fox jumps over the lazy dog. ".repeat(40);
    let d = rt(&t);
    assert!(d.len() < stored_size(t.len()));
    eprintln!(
        "text {} -> {} (stored {})",
        t.len(),
        d.len(),
        stored_size(t.len())
    );
}
