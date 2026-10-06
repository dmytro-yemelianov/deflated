//! M7b fix wave: the single-pass `emit_blocks` (frequency-derived sizes,
//! O(1) symbol tables) must emit exactly the bytes of the original
//! five-pass implementation. `reference` is that implementation, copied
//! verbatim from b73b887 (only the symbol lookups are renamed so they do not
//! depend on the new tables).

use deflate_core::encode_dynamic::emit_blocks;
use deflate_core::encode_fixed::{dist_sym, length_sym};
use deflate_core::tokens::Token;

mod reference {
    use deflate_core::bitwriter::BitWriter;
    use deflate_core::block::CL_ORDER;
    use deflate_core::huffman_build::{
        ClSym, UsedSymbols, build_lengths, canonical_codes, rle_lengths, valid_lengths,
    };
    use deflate_core::lz77::{DIST_BASE, DIST_EXTRA, LENGTH_BASE, LENGTH_EXTRA};
    use deflate_core::tokens::Token;

    fn slot(base: &[u16], v: u16) -> usize {
        base.iter().rposition(|&b| b <= v).unwrap_or(0)
    }

    pub fn length_sym(len: u16) -> (u16, u32, u32) {
        let i = slot(&LENGTH_BASE, len);
        let base = LENGTH_BASE.get(i).copied().unwrap_or(0);
        let nb = LENGTH_EXTRA.get(i).copied().unwrap_or(0);
        (
            257 + i as u16,
            u32::from(len.saturating_sub(base)),
            u32::from(nb),
        )
    }

    pub fn dist_sym(dist: u16) -> (u16, u32, u32) {
        let i = slot(&DIST_BASE, dist);
        let base = DIST_BASE.get(i).copied().unwrap_or(0);
        let nb = DIST_EXTRA.get(i).copied().unwrap_or(0);
        (
            i as u16,
            u32::from(dist.saturating_sub(base)),
            u32::from(nb),
        )
    }

    fn put_litlen(w: &mut BitWriter, sym: u16) {
        let s = u32::from(sym);
        match sym {
            0..=143 => w.write_code(0x30 + s, 8),
            144..=255 => w.write_code(0x190 + (s - 144), 9),
            256..=279 => w.write_code(s - 256, 7),
            _ => w.write_code(0xC0 + (s - 280), 8),
        }
    }

    fn emit_fixed_block(w: &mut BitWriter, final_: bool, tokens: &[Token]) {
        w.write_bits(u32::from(final_), 1);
        w.write_bits(1, 2);
        for t in tokens {
            match *t {
                Token::Literal(b) => put_litlen(w, u16::from(b)),
                Token::Match { len, dist } => {
                    let (ls, le, ln) = length_sym(len);
                    put_litlen(w, ls);
                    w.write_bits(le, ln);
                    let (ds, de, dn) = dist_sym(dist);
                    w.write_code(u32::from(ds), 5);
                    w.write_bits(de, dn);
                }
            }
        }
        put_litlen(w, 256);
    }

    fn used_from_tokens(tokens: &[Token]) -> UsedSymbols {
        let mut u = UsedSymbols::new();
        u.mark_lit(256);
        for t in tokens {
            match *t {
                Token::Literal(b) => u.mark_lit(u16::from(b)),
                Token::Match { len, dist } => {
                    u.mark_lit(length_sym(len).0);
                    u.mark_dist(dist_sym(dist).0);
                }
            }
        }
        u
    }

    fn trim(ls: &mut Vec<u8>, min: usize) {
        let n = ls.iter().rposition(|&l| l != 0).map_or(0, |i| i + 1);
        ls.truncate(n.max(min));
    }

    pub fn lengths_for(tokens: &[Token]) -> Option<(Vec<u8>, Vec<u8>, Vec<u8>)> {
        let mut lf = [0u32; 286];
        let mut df = [0u32; 30];
        lf[256] = 1;
        let mut matches = false;
        for t in tokens {
            match *t {
                Token::Literal(b) => lf[usize::from(b)] += 1,
                Token::Match { len, dist } => {
                    matches = true;
                    if let Some(f) = lf.get_mut(usize::from(length_sym(len).0)) {
                        *f += 1;
                    }
                    if let Some(f) = df.get_mut(usize::from(dist_sym(dist).0)) {
                        *f += 1;
                    }
                }
            }
        }
        let mut lit = build_lengths(&lf, 15);
        let mut dist = if matches {
            build_lengths(&df, 15)
        } else {
            let mut d = vec![0u8; 30];
            d[0] = 1;
            d
        };
        trim(&mut lit, 257);
        trim(&mut dist, 1);
        let mut all = lit.clone();
        all.extend_from_slice(&dist);
        let mut cf = [0u32; 19];
        for s in rle_lengths(&all) {
            cf[usize::from(s.symbol())] += 1;
        }
        let mut cl = build_lengths(&cf, 7);
        let used: Vec<usize> = (0..19).filter(|&i| cf[i] > 0).collect();
        if let [only] = used[..] {
            cl[usize::from(only == 0)] = 1;
        }
        if valid_lengths(&lit, &dist, &cl, &used_from_tokens(tokens)) {
            Some((lit, dist, cl))
        } else {
            None
        }
    }

    fn len_at(codes: &[(u16, u8)], s: usize) -> (u32, u32) {
        codes
            .get(s)
            .map_or((0, 0), |&(c, l)| (u32::from(c), u32::from(l)))
    }

    fn hclen(cl: &[u8]) -> usize {
        let last = CL_ORDER
            .iter()
            .rposition(|&s| cl.get(s).copied().unwrap_or(0) != 0)
            .map_or(0, |i| i + 1);
        last.max(4) - 4
    }

    fn extra(s: ClSym) -> (u32, u32) {
        match s {
            ClSym::Len(_) => (0, 0),
            ClSym::Rep16(v) => (u32::from(v), 2),
            ClSym::Zeros17(v) => (u32::from(v), 3),
            ClSym::Zeros18(v) => (u32::from(v), 7),
        }
    }

    fn emit_dynamic_block(
        w: &mut BitWriter,
        final_: bool,
        lit: &[u8],
        dist: &[u8],
        cl: &[u8],
        tokens: &[Token],
    ) {
        w.write_bits(u32::from(final_), 1);
        w.write_bits(2, 2);
        w.write_bits(lit.len().saturating_sub(257) as u32, 5);
        w.write_bits(dist.len().saturating_sub(1) as u32, 5);
        let hc = hclen(cl);
        w.write_bits(hc as u32, 4);
        for &s in CL_ORDER.iter().take(hc + 4) {
            w.write_bits(u32::from(cl.get(s).copied().unwrap_or(0)), 3);
        }
        let clc = canonical_codes(cl);
        let mut all = lit.to_vec();
        all.extend_from_slice(dist);
        for s in rle_lengths(&all) {
            let (c, l) = len_at(&clc, usize::from(s.symbol()));
            w.write_code(c, l);
            let (v, n) = extra(s);
            w.write_bits(v, n);
        }
        let lc = canonical_codes(lit);
        let dc = canonical_codes(dist);
        for t in tokens {
            match *t {
                Token::Literal(b) => {
                    let (c, l) = len_at(&lc, usize::from(b));
                    w.write_code(c, l);
                }
                Token::Match { len, dist } => {
                    let (ls, le, ln) = length_sym(len);
                    let (c, l) = len_at(&lc, usize::from(ls));
                    w.write_code(c, l);
                    w.write_bits(le, ln);
                    let (ds, de, dn) = dist_sym(dist);
                    let (c, l) = len_at(&dc, usize::from(ds));
                    w.write_code(c, l);
                    w.write_bits(de, dn);
                }
            }
        }
        let (c, l) = len_at(&lc, 256);
        w.write_code(c, l);
    }

    pub fn fixed_bits(tokens: &[Token]) -> usize {
        let lit = |s: u16| match s {
            0..=143 => 8,
            144..=255 => 9,
            256..=279 => 7,
            _ => 8,
        };
        let mut n = 3 + lit(256);
        for t in tokens {
            n += match *t {
                Token::Literal(b) => lit(u16::from(b)),
                Token::Match { len, dist } => {
                    let (ls, _, ln) = length_sym(len);
                    let (_, _, dn) = dist_sym(dist);
                    lit(ls) + ln as usize + 5 + dn as usize
                }
            };
        }
        n
    }

    pub fn dynamic_bits(lit: &[u8], dist: &[u8], cl: &[u8], tokens: &[Token]) -> usize {
        let at = |ls: &[u8], s: u16| usize::from(ls.get(usize::from(s)).copied().unwrap_or(0));
        let mut n = 3 + 14 + 3 * (hclen(cl) + 4);
        let mut all = lit.to_vec();
        all.extend_from_slice(dist);
        for s in rle_lengths(&all) {
            n += at(cl, u16::from(s.symbol())) + extra(s).1 as usize;
        }
        n += at(lit, 256);
        for t in tokens {
            n += match *t {
                Token::Literal(b) => at(lit, u16::from(b)),
                Token::Match { len, dist: d } => {
                    let (ls, _, ln) = length_sym(len);
                    let (ds, _, dn) = dist_sym(d);
                    at(lit, ls) + ln as usize + at(dist, ds) + dn as usize
                }
            };
        }
        n
    }

    fn emit_block(w: &mut BitWriter, final_: bool, tokens: &[Token]) {
        if let Some((lit, dist, cl)) = lengths_for(tokens)
            && dynamic_bits(&lit, &dist, &cl, tokens) < fixed_bits(tokens)
        {
            emit_dynamic_block(w, final_, &lit, &dist, &cl, tokens);
        } else {
            emit_fixed_block(w, final_, tokens);
        }
    }

    pub fn emit_blocks(tokens: &[Token]) -> Vec<u8> {
        let mut w = BitWriter::new();
        let mut chunks = tokens.chunks(16384).peekable();
        if chunks.peek().is_none() {
            emit_block(&mut w, true, &[]);
        }
        while let Some(c) = chunks.next() {
            emit_block(&mut w, chunks.peek().is_none(), c);
        }
        w.finish()
    }
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

/// Token streams in several shapes. Matches need not be expandable: the
/// emitter only maps tokens to symbols. `wild` adds out-of-contract
/// lengths and distances (any u16), which the oracle can also send.
fn stream(rng: &mut Rng, n: usize, mode: u64) -> Vec<Token> {
    let fib = [
        1u64, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597,
    ];
    (0..n)
        .map(|_| match mode {
            // uniform literals and matches
            0 => {
                if rng.below(2) == 0 {
                    Token::Literal(rng.below(256) as u8)
                } else {
                    Token::Match {
                        len: 3 + rng.below(256) as u16,
                        dist: 1 + rng.below(32768) as u16,
                    }
                }
            }
            // Fibonacci-skewed, forcing the length limiter
            1 => {
                let r = rng.below(fib.iter().sum());
                let mut acc = 0;
                let i = fib
                    .iter()
                    .position(|&f| {
                        acc += f;
                        r < acc
                    })
                    .unwrap_or(0);
                if rng.below(3) == 0 {
                    Token::Match {
                        len: 3 + i as u16 * 15,
                        dist: 1 << i.min(15),
                    }
                } else {
                    Token::Literal(i as u8 * 13)
                }
            }
            // a single literal
            2 => Token::Literal(b'a'),
            // literals only
            3 => Token::Literal(rng.below(256) as u8),
            // match heavy, short lengths and distances
            4 => {
                if rng.below(10) < 7 {
                    Token::Match {
                        len: 3 + rng.below(12) as u16,
                        dist: 1 + rng.below(64) as u16,
                    }
                } else {
                    Token::Literal(b'a' + rng.below(26) as u8)
                }
            }
            // out of contract: any u16 length and distance
            _ => {
                if rng.below(2) == 0 {
                    Token::Literal(rng.below(256) as u8)
                } else {
                    Token::Match {
                        len: rng.below(65536) as u16,
                        dist: rng.below(65536) as u16,
                    }
                }
            }
        })
        .collect()
}

#[test]
fn symbol_tables_match_linear_scan_for_every_u16() {
    for v in 0..=u16::MAX {
        assert_eq!(length_sym(v), reference::length_sym(v), "len {v}");
        assert_eq!(dist_sym(v), reference::dist_sym(v), "dist {v}");
    }
}

#[test]
fn single_pass_emit_blocks_matches_reference() {
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    let sizes = [
        0usize, 1, 2, 3, 50, 100, 1000, 16383, 16384, 16385, 32768, 40000,
    ];
    let mut cases = 0;
    for &n in &sizes {
        for mode in 0..6 {
            let ts = stream(&mut rng, n, mode);
            assert_eq!(
                emit_blocks(&ts),
                reference::emit_blocks(&ts),
                "n={n} mode={mode}"
            );
            cases += 1;
        }
    }
    for _ in 0..300 {
        let n = rng.below(3000) as usize;
        let mode = rng.below(6);
        let ts = stream(&mut rng, n, mode);
        assert_eq!(
            emit_blocks(&ts),
            reference::emit_blocks(&ts),
            "n={n} mode={mode}"
        );
        cases += 1;
    }
    assert!(cases > 300);
}

#[test]
fn lengths_and_bit_counts_match_reference() {
    use deflate_core::encode_dynamic::{dynamic_bits, fixed_bits, lengths_for};
    let mut rng = Rng(42);
    for _ in 0..400 {
        let n = rng.below(5000) as usize;
        let mode = rng.below(6);
        let ts = stream(&mut rng, n, mode);
        let got = lengths_for(&ts);
        assert_eq!(got, reference::lengths_for(&ts), "n={n} mode={mode}");
        assert_eq!(fixed_bits(&ts), reference::fixed_bits(&ts));
        if let Some((l, d, c)) = got {
            assert_eq!(
                dynamic_bits(&l, &d, &c, &ts),
                reference::dynamic_bits(&l, &d, &c, &ts)
            );
        }
    }
}
