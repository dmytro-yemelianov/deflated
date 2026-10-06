//! M7b Task 5: length heuristic, canonical codes, RLE, validity.

use deflate_core::bitstream::BitReader;
use deflate_core::bitwriter::BitWriter;
use deflate_core::huffman::{Completeness, HuffmanTable};
use deflate_core::huffman_build::{
    ClSym, UsedSymbols, build_lengths, canonical_codes, rle_lengths, valid_lengths,
};
use deflate_core::tokens::Token;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

fn kraft(lengths: &[u8]) -> u64 {
    lengths
        .iter()
        .filter(|&&l| l > 0)
        .map(|&l| 1u64 << (15 - l))
        .sum()
}

fn check_build(freqs: &[u32], max_len: u8) -> Vec<u8> {
    let ls = build_lengths(freqs, max_len);
    assert_eq!(ls.len(), freqs.len());
    let mut used = 0;
    for (f, l) in freqs.iter().zip(&ls) {
        assert!(*l <= max_len);
        assert_eq!(*f > 0, *l > 0, "freq {f} len {l}");
        used += usize::from(*f > 0);
    }
    if used >= 2 {
        assert_eq!(kraft(&ls), 1 << 15, "{freqs:?} -> {ls:?}");
    }
    ls
}

#[test]
fn build_edge_cases() {
    assert_eq!(build_lengths(&[], 15), Vec::<u8>::new());
    assert_eq!(build_lengths(&[0, 0, 0], 15), vec![0, 0, 0]);
    assert_eq!(check_build(&[0, 5, 0], 15), vec![0, 1, 0]);
    assert_eq!(check_build(&[3, 3], 15), vec![1, 1]);
    assert_eq!(check_build(&[7; 8], 15), vec![3; 8]);
    check_build(&[1; 286], 15);
    check_build(&[9; 19], 7);
}

#[test]
fn build_geometric_limited() {
    for max in [7u8, 9, 15] {
        let freqs: Vec<u32> = (0..28).map(|k| 1u32 << k).collect();
        check_build(&freqs, max);
        let mut rev = freqs.clone();
        rev.reverse();
        check_build(&rev, max);
    }
    let fib: Vec<u32> = {
        let (mut a, mut b) = (1u32, 1u32);
        (0..40)
            .map(|_| {
                let r = a;
                let t = a.saturating_add(b);
                a = b;
                b = t;
                r
            })
            .collect()
    };
    check_build(&fib, 15);
    check_build(&fib, 7);
}

#[test]
fn build_random() {
    let mut rng = Rng(0x1234_5678_9abc_def1);
    for _ in 0..500 {
        let n = 2 + rng.below(285);
        let max = if n <= 128 {
            [7u8, 15][rng.below(2)]
        } else {
            15
        };
        let freqs: Vec<u32> = (0..n)
            .map(|_| match rng.below(4) {
                0 => 0,
                1 => 1 + rng.below(3) as u32,
                2 => 1 + rng.below(1000) as u32,
                _ => 1 << rng.below(24),
            })
            .collect();
        check_build(&freqs, max);
    }
}

#[test]
fn canonical_codes_decode() {
    let mut rng = Rng(42);
    for _ in 0..300 {
        let n = 2 + rng.below(285);
        let freqs: Vec<u32> = (0..n).map(|_| rng.below(500) as u32).collect();
        if freqs.iter().filter(|&&f| f > 0).count() < 2 {
            continue;
        }
        let ls = build_lengths(&freqs, 15);
        let codes = canonical_codes(&ls);
        assert_eq!(codes.len(), ls.len());
        let table = HuffmanTable::from_lengths(&ls, Completeness::Complete).unwrap();
        let syms: Vec<usize> = (0..ls.len()).filter(|&s| ls[s] > 0).collect();
        let mut w = BitWriter::new();
        for &s in &syms {
            assert_eq!(codes[s].1, ls[s]);
            w.write_code(u32::from(codes[s].0), u32::from(codes[s].1));
        }
        let bytes = w.finish();
        let mut r = BitReader::new(&bytes);
        for &s in &syms {
            assert_eq!(table.decode(&mut r).unwrap() as usize, s);
        }
    }
}

#[test]
fn canonical_rfc_example() {
    // RFC 1951 §3.2.2: A..H = 3,3,3,3,3,2,4,4.
    let c = canonical_codes(&[3, 3, 3, 3, 3, 2, 4, 4]);
    let want = [
        (0b010, 3),
        (0b011, 3),
        (0b100, 3),
        (0b101, 3),
        (0b110, 3),
        (0b00, 2),
        (0b1110, 4),
        (0b1111, 4),
    ];
    assert_eq!(c, want.to_vec());
    assert_eq!(canonical_codes(&[0, 2, 0]), vec![(0, 0), (0, 2), (0, 0)]);
}

fn expand(syms: &[ClSym]) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::new();
    for s in syms {
        match *s {
            ClSym::Len(v) => out.push(v),
            ClSym::Rep16(e) => {
                let p = *out.last().unwrap();
                out.extend(std::iter::repeat_n(p, usize::from(e) + 3));
            }
            ClSym::Zeros17(e) => out.extend(std::iter::repeat_n(0, usize::from(e) + 3)),
            ClSym::Zeros18(e) => out.extend(std::iter::repeat_n(0, usize::from(e) + 11)),
        }
    }
    out
}

use ClSym::{Len, Rep16, Zeros17, Zeros18};

#[test]
fn rle_golden() {
    assert_eq!(rle_lengths(&[]), vec![]);
    // Zeros.
    assert_eq!(rle_lengths(&[0]), vec![Len(0)]);
    assert_eq!(rle_lengths(&[0; 2]), vec![Len(0), Len(0)]);
    assert_eq!(rle_lengths(&[0; 3]), vec![Zeros17(0)]);
    assert_eq!(rle_lengths(&[0; 6]), vec![Zeros17(3)]);
    assert_eq!(rle_lengths(&[0; 10]), vec![Zeros17(7)]);
    assert_eq!(rle_lengths(&[0; 11]), vec![Zeros18(0)]);
    assert_eq!(rle_lengths(&[0; 138]), vec![Zeros18(127)]);
    assert_eq!(rle_lengths(&[0; 139]), vec![Zeros18(127), Len(0)]);
    assert_eq!(rle_lengths(&[0; 140]), vec![Zeros18(127), Len(0), Len(0)]);
    assert_eq!(rle_lengths(&[0; 141]), vec![Zeros18(127), Zeros17(0)]);
    // 150 = 138 + 12 -> 18, 18(1)
    assert_eq!(rle_lengths(&[0; 150]), vec![Zeros18(127), Zeros18(1)]);
    // Non-zeros.
    assert_eq!(rle_lengths(&[5]), vec![Len(5)]);
    assert_eq!(rle_lengths(&[5; 2]), vec![Len(5), Len(5)]);
    assert_eq!(rle_lengths(&[5; 3]), vec![Len(5), Len(5), Len(5)]);
    assert_eq!(rle_lengths(&[5; 4]), vec![Len(5), Rep16(0)]);
    assert_eq!(rle_lengths(&[5; 7]), vec![Len(5), Rep16(3)]);
    assert_eq!(rle_lengths(&[5; 8]), vec![Len(5), Rep16(3), Len(5)]);
    assert_eq!(rle_lengths(&[5; 10]), vec![Len(5), Rep16(3), Rep16(0)]);
    assert_eq!(rle_lengths(&[5; 11]), vec![Len(5), Rep16(3), Rep16(1)]);
    assert_eq!(rle_lengths(&[5; 138]).len(), 1 + 22 + 1);
    assert_eq!(
        rle_lengths(&[1, 1, 0, 0, 0, 2]),
        vec![Len(1), Len(1), Zeros17(0), Len(2)]
    );
}

#[test]
fn rle_expands_back() {
    for n in [1usize, 2, 3, 6, 7, 10, 11, 138, 139, 140, 141, 276, 300] {
        for v in [0u8, 1, 8, 15] {
            let a = vec![v; n];
            assert_eq!(expand(&rle_lengths(&a)), a, "v={v} n={n}");
            let mut b = vec![3u8; 5];
            b.extend(&a);
            b.push(4);
            assert_eq!(expand(&rle_lengths(&b)), b);
        }
    }
    let mut rng = Rng(7);
    for _ in 0..300 {
        let n = 1 + rng.below(316);
        let mut a = Vec::new();
        while a.len() < n {
            let v = [0u8, 0, 0, 1, 5, 15][rng.below(6)];
            let run = 1 + rng.below(20);
            a.extend(std::iter::repeat_n(v, run));
        }
        assert_eq!(expand(&rle_lengths(&a)), a);
    }
}

fn used_for(tokens: &[Token]) -> UsedSymbols {
    UsedSymbols::from_tokens(tokens)
}

fn fixed_lit() -> Vec<u8> {
    let mut l = vec![8u8; 288];
    l[144..256].fill(9);
    l[256..280].fill(7);
    l.truncate(286);
    l
}

#[test]
fn valid_lengths_cases() {
    let toks = [Token::Literal(b'a'), Token::Match { len: 3, dist: 1 }];
    let used = used_for(&toks);
    let lit = fixed_lit(); // 286 entries: 8x(0..144) 9x 7x(256..280) 8x(280..286); complete? see below
    let dist = vec![5u8; 30];
    let cl = vec![5u8, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4, 4, 4];
    // Truncating the fixed code to 286 is not complete (288 symbols needed).
    assert!(!valid_lengths(&lit, &dist, &cl, &used));

    let freqs: Vec<u32> = (0..286)
        .map(|i| {
            if i < 100 || i == 256 || i == 257 {
                3
            } else {
                0
            }
        })
        .collect();
    let lit = build_lengths(&freqs, 15);
    let dist = build_lengths(&[4, 0, 0, 0], 15); // single symbol, degenerate
    let mut all = lit.clone();
    all.extend(&dist);
    let mut cf = [0u32; 19];
    for s in rle_lengths(&all) {
        let i = match s {
            Len(v) => usize::from(v),
            Rep16(_) => 16,
            Zeros17(_) => 17,
            Zeros18(_) => 18,
        };
        cf[i] += 1;
    }
    let cl = build_lengths(&cf, 7);
    let toks = [Token::Literal(b'a'), Token::Match { len: 3, dist: 1 }];
    let used = used_for(&toks);
    assert!(valid_lengths(&lit, &dist, &cl, &used));

    // Symbol used but no code.
    let used2 = used_for(&[Token::Literal(200)]);
    assert!(!valid_lengths(&lit, &dist, &cl, &used2));
    // Distance symbol used with zero length.
    let used3 = used_for(&[Token::Match { len: 3, dist: 2 }]);
    assert!(!valid_lengths(&lit, &dist, &cl, &used3));
    // Sizes.
    assert!(!valid_lengths(&lit[..256], &dist, &cl, &used));
    assert!(!valid_lengths(&lit, &[], &cl, &used));
    assert!(!valid_lengths(&lit, &dist, &cl[..18], &used));
    // CL symbol used by RLE but with zero CL length.
    let mut cl2 = cl.clone();
    cl2[0] = 0;
    let used = used_for(&toks);
    assert!(!valid_lengths(&lit, &dist, &cl2, &used) || cf[0] == 0);
    // Over-limit CL length.
    let mut cl3 = vec![0u8; 19];
    cl3[0] = 8;
    assert!(!valid_lengths(&lit, &dist, &cl3, &used));
}

/// zlib accepts an incomplete distance code only when no length exceeds 1
/// (one used symbol of length 1, or none). `valid_lengths` must not accept
/// a lone distance code of length 2..=15, which our decoder would read but
/// zlib rejects ("invalid distances set").
#[test]
fn valid_lengths_lone_distance_code_must_have_length_one() {
    let lf: Vec<u32> = (0..286)
        .map(|i| u32::from(i < 100 || i == 256 || i == 258))
        .collect();
    let lit = build_lengths(&lf, 15);
    let lit_only = used_for(&[Token::Literal(b'a')]);
    let with_match = used_for(&[Token::Literal(b'a'), Token::Match { len: 4, dist: 1 }]);
    let cl_for = |dist: &[u8]| {
        let mut all = lit.clone();
        all.extend(dist);
        let mut cf = [0u32; 19];
        for s in rle_lengths(&all) {
            cf[usize::from(s.symbol())] += 1;
        }
        let mut cl = build_lengths(&cf, 7);
        if cf.iter().filter(|&&n| n > 0).count() == 1 {
            let only = cf.iter().position(|&n| n > 0).unwrap();
            cl[usize::from(only == 0)] = 1;
        }
        cl
    };
    for l in 1..=15u8 {
        let dist = [l];
        let cl = cl_for(&dist);
        assert_eq!(
            valid_lengths(&lit, &dist, &cl, &with_match),
            l == 1,
            "len {l}"
        );
        assert_eq!(
            valid_lengths(&lit, &dist, &cl, &lit_only),
            l == 1,
            "len {l}"
        );
        let mut dist = vec![0u8; 30];
        dist[0] = l;
        let cl = cl_for(&dist);
        assert_eq!(
            valid_lengths(&lit, &dist, &cl, &with_match),
            l == 1,
            "len {l}, 30"
        );
    }
    // No distance code at all: zlib accepts it, and so do we when no match
    // needs one.
    let dist = [0u8];
    let cl = cl_for(&dist);
    assert!(valid_lengths(&lit, &dist, &cl, &lit_only));
    assert!(!valid_lengths(&lit, &dist, &cl, &with_match));
    // Complete codes are unaffected.
    let dist = [1u8, 1];
    let cl = cl_for(&dist);
    assert!(valid_lengths(&lit, &dist, &cl, &with_match));
    let dist = [1u8, 2, 2];
    let cl = cl_for(&dist);
    assert!(valid_lengths(&lit, &dist, &cl, &with_match));
    // Incomplete with two used symbols stays invalid.
    let dist = [2u8, 2];
    let cl = cl_for(&dist);
    assert!(!valid_lengths(&lit, &dist, &cl, &with_match));
}

#[test]
fn used_symbols_marks() {
    let u = used_for(&[
        Token::Literal(7),
        Token::Match {
            len: 258,
            dist: 32768,
        },
    ]);
    assert!(u.lit(7) && u.lit(256) && u.lit(285) && u.dist(29));
    assert!(!u.lit(8) && !u.dist(0));
}
