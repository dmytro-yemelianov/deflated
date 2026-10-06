use deflate_core::bitwriter::BitWriter;
use deflate_core::compress::default_split_for;
use deflate_core::encode_dynamic::{BLOCK_TOKENS, emit_blocks, emit_blocks_iter};
use deflate_core::encode_fixed::emit_fixed_block;
use deflate_core::tokens::{Token, expand};
use std::cell::RefCell;

thread_local! {
    static WINDOWS: RefCell<Vec<Vec<Token>>> = const { RefCell::new(Vec::new()) };
}

fn content_split(ts: &[Token]) -> Option<usize> {
    WINDOWS.with(|w| w.borrow_mut().push(ts.to_vec()));
    match ts.first() {
        Some(Token::Literal(b)) => Some(usize::from(*b)),
        Some(Token::Match { .. }) => Some(1),
        None => None,
    }
}

fn fixed_chunks(ts: &[Token], sizes: &[usize]) -> Vec<u8> {
    let mut w = BitWriter::new();
    let mut start = 0;
    for (i, &n) in sizes.iter().enumerate() {
        emit_fixed_block(
            &mut w,
            i + 1 == sizes.len(),
            ts[start..start + n].iter().copied(),
        );
        start += n;
    }
    assert_eq!(start, ts.len());
    w.finish()
}

fn roundtrip(bytes: &[u8], ts: &[Token]) {
    let expected = expand(ts).unwrap();
    assert_eq!(deflate_core::inflate(bytes).unwrap(), expected);
    assert_eq!(
        miniz_oxide::inflate::decompress_to_vec(bytes).unwrap(),
        expected
    );
}

#[test]
fn callback_sees_remaining_content_and_selects_exact_boundaries() {
    WINDOWS.with(|w| w.borrow_mut().clear());
    let ts = [2, 9, 1, 3, 8, 7].map(Token::Literal);
    let got = emit_blocks(&ts, content_split);
    WINDOWS.with(|w| {
        assert_eq!(
            *w.borrow(),
            vec![ts.to_vec(), ts[2..].to_vec(), ts[3..].to_vec()]
        )
    });
    assert_eq!(got, fixed_chunks(&ts, &[2, 1, 3]));
    roundtrip(&got, &ts);
}

#[test]
fn empty_and_exact_custom_boundaries_have_one_final_block() {
    fn two(_: &[Token]) -> Option<usize> {
        Some(2)
    }
    for n in 0..=5 {
        let ts = vec![Token::Literal(7); n];
        let mut sizes = vec![2; n / 2];
        if n % 2 != 0 {
            sizes.push(1);
        }
        if sizes.is_empty() {
            sizes.push(0);
        }
        let got = emit_blocks(&ts, two);
        assert_eq!(got, fixed_chunks(&ts, &sizes));
        roundtrip(&got, &ts);
    }
}

#[test]
fn invalid_splits_fall_back_to_default_bytes() {
    fn zero(_: &[Token]) -> Option<usize> {
        Some(0)
    }
    fn oversized(_: &[Token]) -> Option<usize> {
        Some(BLOCK_TOKENS + 1)
    }
    fn huge(_: &[Token]) -> Option<usize> {
        Some(usize::MAX)
    }
    for n in [
        0,
        1,
        BLOCK_TOKENS - 1,
        BLOCK_TOKENS,
        BLOCK_TOKENS + 1,
        2 * BLOCK_TOKENS,
    ] {
        let ts = vec![Token::Literal(42); n];
        let expected = emit_blocks(&ts, default_split_for);
        for split in [
            zero as fn(&[Token]) -> Option<usize>,
            oversized,
            huge,
            default_split_for,
        ] {
            assert_eq!(emit_blocks_iter(ts.iter().copied(), split), expected);
        }
    }
}

#[test]
fn lookahead_is_bounded_and_refilled_at_each_boundary() {
    WINDOWS.with(|w| w.borrow_mut().clear());
    let ts = vec![Token::Literal(255); BLOCK_TOKENS + 300];
    let got = emit_blocks_iter(ts.iter().copied(), content_split);
    WINDOWS.with(|w| {
        let windows = w.borrow();
        for (i, window) in windows.iter().enumerate() {
            assert_eq!(
                window.as_slice(),
                &ts[i * 255..(i * 255 + BLOCK_TOKENS).min(ts.len())]
            );
        }
        assert_eq!(windows.len(), ts.len().div_ceil(255));
    });
    roundtrip(&got, &ts);
}

#[test]
fn custom_split_preserves_cross_block_matches() {
    fn one(_: &[Token]) -> Option<usize> {
        Some(1)
    }
    let ts = [
        Token::Literal(b'a'),
        Token::Literal(b'b'),
        Token::Match { len: 258, dist: 2 },
        Token::Match { len: 10, dist: 260 },
    ];
    let got = emit_blocks(&ts, one);
    assert_eq!(got, fixed_chunks(&ts, &[1, 1, 1, 1]));
    roundtrip(&got, &ts);
}
