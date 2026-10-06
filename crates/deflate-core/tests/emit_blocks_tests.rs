//! M7b Task 6: lengths_for, emit_dynamic_block, emit_blocks, deflate.

use deflate_core::bitwriter::BitWriter;
use deflate_core::deflate;
use deflate_core::encode_dynamic::{
    dynamic_bits, emit_blocks, emit_dynamic_block, fixed_bits, lengths_for,
};
use deflate_core::encode_fixed::{emit_fixed, emit_fixed_block};
use deflate_core::inflate;
use deflate_core::matcher::tokens;
use deflate_core::tokens::{Token, expand};

fn rand_bytes(n: usize, seed: u64) -> Vec<u8> {
    let mut s = seed;
    (0..n)
        .map(|_| {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            s as u8
        })
        .collect()
}

fn english(n: usize) -> Vec<u8> {
    let words = [
        "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog", "and", "then", "runs",
        "away", "from", "a", "very", "angry", "farmer", "who", "had", "lost", "his", "hat",
    ];
    let mut s = 12345u64;
    let mut out = Vec::new();
    while out.len() < n {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        out.extend_from_slice(words[(s % words.len() as u64) as usize].as_bytes());
        out.push(if s % 13 == 0 { b'.' } else { b' ' });
    }
    out.truncate(n);
    out
}

/// Both our decoder and an independent one must agree.
fn check_stream(stream: &[u8], want: &[u8]) {
    assert_eq!(inflate(stream).unwrap(), want);
    assert_eq!(
        miniz_oxide::inflate::decompress_to_vec(stream).expect("independent decoder"),
        want
    );
}

fn check_tokens(ts: &[Token]) -> Vec<u8> {
    let want = expand(ts).unwrap();
    let s = emit_blocks(ts);
    check_stream(&s, &want);
    s
}

#[test]
fn emit_blocks_empty_and_no_matches() {
    check_tokens(&[]);
    let lits: Vec<Token> = b"hello hello world"
        .iter()
        .map(|&b| Token::Literal(b))
        .collect();
    check_tokens(&lits);
    // Lengths for a no-match block: the distance code is one symbol of length 1.
    let (_, d, _) = lengths_for(&lits).unwrap();
    assert_eq!(d, vec![1]);
    // Single repeated byte, as literals and as a match chain.
    check_tokens(&[Token::Literal(7); 50]);
    let mut ts = vec![Token::Literal(7)];
    ts.extend(std::iter::repeat_n(Token::Match { len: 258, dist: 1 }, 20));
    check_tokens(&ts);
}

#[test]
fn single_symbol_blocks() {
    // Only 256 is used besides one literal: lone-symbol corner cases.
    check_tokens(&[Token::Literal(0)]);
    check_tokens(&[Token::Literal(255)]);
    check_tokens(&[Token::Literal(1), Token::Match { len: 3, dist: 1 }]);
}

#[test]
fn block_boundaries_16383_16384_16385() {
    for n in [16383usize, 16384, 16385, 32768, 32769] {
        let mut ts: Vec<Token> = Vec::new();
        let r = rand_bytes(n, 9);
        for (i, &b) in r.iter().enumerate() {
            // Mix literals and matches (dist 1 always valid after the first token).
            if i > 0 && i % 3 == 0 {
                ts.push(Token::Match {
                    len: 3 + (b % 50) as u16,
                    dist: 1,
                });
            } else {
                ts.push(Token::Literal(b % 16));
            }
        }
        check_tokens(&ts);
    }
}

#[test]
fn matches_reach_back_across_blocks() {
    let mut ts: Vec<Token> = (0..16384u32)
        .map(|i| Token::Literal((i % 200) as u8))
        .collect();
    ts.push(Token::Match {
        len: 258,
        dist: 16384,
    });
    ts.push(Token::Match { len: 10, dist: 100 });
    check_tokens(&ts);
}

#[test]
fn deflate_roundtrips_review_inputs() {
    let mut cases: Vec<Vec<u8>> = vec![vec![], vec![b'a'], vec![7; 300], b"abc".repeat(200)];
    for n in [65534usize, 65535, 65536, 65537, 131071, 131072] {
        cases.push(rand_bytes(n, 7));
        cases.push(vec![b'a'; n]);
        cases.push(english(n));
    }
    cases.push(vec![0u8; 1 << 20]);
    cases.push(b"xy".repeat(100_000));
    let p = rand_bytes(32768, 5);
    let mut x = p.clone();
    x.extend_from_slice(&p[..258]);
    cases.push(x);
    for c in cases {
        let d = deflate(&c);
        check_stream(&d, &c);
        assert!(d.len() <= c.len() + 5 * c.len().div_ceil(65535).max(1));
    }
}

#[test]
fn lengths_for_output_is_trimmed_and_sized() {
    let t = english(5000);
    let ts: Vec<Token> = tokens(&t).collect();
    let (lit, dist, cl) = lengths_for(&ts).unwrap();
    assert!((257..=286).contains(&lit.len()));
    assert!(*lit.last().unwrap() != 0 || lit.len() == 257);
    assert!(*dist.last().unwrap() != 0 || dist.len() == 1);
    assert_eq!(cl.len(), 19);
}

#[test]
fn bit_counts_are_exact() {
    for n in [0usize, 1, 100, 5000, 40000] {
        let t = english(n);
        let ts: Vec<Token> = tokens(&t).collect();
        let mut w = BitWriter::new();
        emit_fixed_block(&mut w, true, ts.iter().copied());
        assert_eq!(w.bit_len(), fixed_bits(&ts), "fixed n={n}");
        if let Some((l, d, c)) = lengths_for(&ts) {
            let mut w = BitWriter::new();
            emit_dynamic_block(&mut w, true, &l, &d, &c, &ts);
            assert_eq!(w.bit_len(), dynamic_bits(&l, &d, &c, &ts), "dyn n={n}");
        }
    }
}

#[test]
fn small_blocks_pick_fixed_and_large_pick_dynamic() {
    // Tiny: header overhead makes fixed win; output equals M7a's fixed block.
    let ts = [Token::Literal(b'a')];
    assert_eq!(emit_blocks(&ts), emit_fixed(ts.iter().copied()));
    // Skewed large input: dynamic must be strictly smaller than fixed.
    let t = english(20000);
    let ts: Vec<Token> = tokens(&t).collect();
    let (l, d, c) = lengths_for(&ts).unwrap();
    assert!(dynamic_bits(&l, &d, &c, &ts) < fixed_bits(&ts));
    assert!(emit_blocks(&ts).len() < emit_fixed(ts.iter().copied()).len());
}

#[test]
fn text_size_m7a_vs_m7b() {
    let t = english(100_000);
    let ts: Vec<Token> = tokens(&t).collect();
    let m7a = emit_fixed(ts.iter().copied()).len();
    let m7b = deflate(&t).len();
    eprintln!("text {} -> M7a {} M7b {}", t.len(), m7a, m7b);
    assert!(m7b < m7a);
}

#[test]
fn random_tokens_fuzz() {
    for seed in 1..40u64 {
        let r = rand_bytes(3000, seed);
        let m = 2 + (seed % 30) as u8;
        let x: Vec<u8> = r.iter().map(|b| b % m).collect();
        let d = deflate(&x);
        check_stream(&d, &x);
    }
}
