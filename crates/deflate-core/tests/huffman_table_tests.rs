//! ADR 0005: the table-driven decode (`decode_fast`, Lean `decodeSymFast`)
//! must agree with the canonical walk (`decode`, Lean `decodeSym`) on every
//! reader, symbol by symbol, positions and errors included. Lean proves that
//! for the model (`decodeSymFast_eq`); these tests check the Rust mirrors it.

use deflate_core::Error;
use deflate_core::bitstream::BitReader;
use deflate_core::huffman::{
    Completeness, HuffmanTable, MAX_CODE_LEN, TABLE_BITS, fixed_dist, fixed_litlen,
};

/// Deterministic xorshift64*, so failures reproduce.
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

/// A random complete code: split random leaves of a full binary tree until
/// it has `n` leaves, then scatter them over an alphabet of `alphabet`.
fn random_complete_lengths(rng: &mut Rng, alphabet: usize) -> Vec<u8> {
    let n = 2 + rng.below(alphabet - 1);
    let mut leaves: Vec<u8> = vec![0];
    while leaves.len() < n {
        let i = rng.below(leaves.len());
        if leaves[i] as usize >= MAX_CODE_LEN {
            // Keep going; another leaf is shallower unless all are at 15,
            // which needs 2^15 leaves and cannot happen for n <= 320.
            continue;
        }
        leaves[i] += 1;
        let d = leaves[i];
        leaves.push(d);
    }
    let mut lengths = vec![0u8; alphabet];
    let mut slots: Vec<usize> = (0..alphabet).collect();
    for l in leaves {
        let k = rng.below(slots.len());
        lengths[slots.swap_remove(k)] = l;
    }
    lengths
}

fn fixed_lit_lengths() -> Vec<u8> {
    let mut l = vec![8u8; 288];
    l[144..256].fill(9);
    l[256..280].fill(7);
    l
}

/// The degenerate distance codes of ADR 0004: empty, and one symbol at
/// every possible length and position.
fn degenerate_codes() -> Vec<Vec<u8>> {
    let mut v = vec![vec![0u8; 30], vec![0u8; 1]];
    for len in 1..=MAX_CODE_LEN as u8 {
        for pos in [0usize, 1, 17, 29] {
            let mut l = vec![0u8; 30];
            l[pos] = len;
            v.push(l);
        }
    }
    v
}

/// Canonical codes, computed independently of `HuffmanTable`.
fn canonical_codes(lengths: &[u8]) -> Vec<u32> {
    let mut bl_count = [0u32; MAX_CODE_LEN + 1];
    for &l in lengths {
        if l != 0 {
            bl_count[l as usize] += 1;
        }
    }
    let mut next = [0u32; MAX_CODE_LEN + 2];
    let mut code = 0u32;
    for bits in 1..=MAX_CODE_LEN {
        code = (code + bl_count[bits - 1]) << 1;
        next[bits] = code;
    }
    lengths
        .iter()
        .map(|&l| {
            if l == 0 {
                return 0;
            }
            let c = next[l as usize];
            next[l as usize] += 1;
            c
        })
        .collect()
}

/// Bits of an encoding of `syms`, one per element, in stream order.
fn encode_bits(lengths: &[u8], syms: &[usize]) -> Vec<u8> {
    let codes = canonical_codes(lengths);
    let mut bits = Vec::new();
    for &s in syms {
        let l = lengths[s];
        for i in (0..l).rev() {
            bits.push(((codes[s] >> i) & 1) as u8);
        }
    }
    bits
}

fn pack(bits: &[u8]) -> Vec<u8> {
    let mut bytes = vec![0u8; bits.len().div_ceil(8)];
    for (i, b) in bits.iter().enumerate() {
        bytes[i / 8] |= b << (i % 8);
    }
    bytes
}

/// A reader over `bytes` positioned at bit `start`.
fn reader_at(bytes: &[u8], start: usize) -> BitReader<'_> {
    let mut r = BitReader::new(&bytes[start / 8..]);
    r.read_bits((start % 8) as u32).unwrap();
    r
}

/// Decode with both paths from bit `start` until either errs; every step
/// must give the same result and leave both readers at the same position.
/// Returns how many symbols were decoded and the terminating error.
fn agree_from(t: &HuffmanTable, bytes: &[u8], start: usize) -> (usize, Error) {
    let mut slow = reader_at(bytes, start);
    let mut fast = reader_at(bytes, start);
    let mut n = 0;
    loop {
        let before = slow.bit_pos();
        let a = t.decode(&mut slow);
        let b = t.decode_fast(&mut fast);
        assert_eq!(a, b, "start {start}, symbol {n}, at bit {before}");
        assert_eq!(
            slow.bit_pos(),
            fast.bit_pos(),
            "start {start}, symbol {n}, at bit {before}: positions differ"
        );
        match a {
            Ok(_) => n += 1,
            Err(e) => return (n, e),
        }
    }
}

fn random_bytes(rng: &mut Rng, n: usize) -> Vec<u8> {
    (0..n).map(|_| rng.next() as u8).collect()
}

// --- The table itself: replication fill against literal evaluation ---

/// ADR 0005, "Table contents": the literal construction. Entry `p` is what
/// the canonical decode does on the stream `[p & 0xff, p >> 8]`.
fn literal_table(t: &HuffmanTable) -> Vec<u16> {
    (0..1usize << TABLE_BITS)
        .map(|p| {
            let bytes = [(p & 0xff) as u8, (p >> 8) as u8];
            let mut r = BitReader::new(&bytes);
            match t.decode(&mut r) {
                Ok(s) if r.bit_pos() <= TABLE_BITS as usize => (s << 4) | r.bit_pos() as u16,
                _ => 0,
            }
        })
        .collect()
}

fn assert_fill_is_literal(lengths: &[u8], c: Completeness) {
    let t = HuffmanTable::from_lengths(lengths, c).unwrap();
    assert_eq!(
        t.fast_table().as_slice(),
        literal_table(&t).as_slice(),
        "lengths {lengths:?}"
    );
}

#[test]
fn fill_matches_literal_evaluation_on_fixed_codes() {
    assert_fill_is_literal(&fixed_lit_lengths(), Completeness::Complete);
    assert_fill_is_literal(&[5u8; 32], Completeness::Complete);
}

#[test]
fn fixed_tables_have_no_fallback_entries() {
    // Lean `fixedLitLen_table_total` and `fixedDist_table_total`.
    assert!(fixed_litlen().fast_table().iter().all(|&e| e != 0));
    assert!(fixed_dist().fast_table().iter().all(|&e| e != 0));
}

#[test]
fn fill_matches_literal_evaluation_on_random_complete_codes() {
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    for i in 0..2000 {
        let alphabet = [2, 3, 19, 30, 286, 288][i % 6];
        let lengths = random_complete_lengths(&mut rng, alphabet);
        assert_fill_is_literal(&lengths, Completeness::Complete);
    }
}

#[test]
fn fill_matches_literal_evaluation_on_degenerate_distance_codes() {
    for lengths in degenerate_codes() {
        assert_fill_is_literal(&lengths, Completeness::AllowDegenerate);
    }
}

#[test]
fn entries_are_hits_only_within_table_bits() {
    // Lean `tableEntry_some`: a hit has 1 <= len <= TABLE_BITS.
    let mut rng = Rng(7);
    for _ in 0..200 {
        let t = HuffmanTable::from_lengths(
            &random_complete_lengths(&mut rng, 288),
            Completeness::Complete,
        )
        .unwrap();
        for &e in t.fast_table().iter() {
            let len = e & 0xf;
            assert!(e == 0 || (1..=TABLE_BITS as u16).contains(&len), "{e:#x}");
        }
    }
}

// --- The decode: table path against the canonical walk ---

#[test]
fn random_bits_under_random_complete_codes() {
    let mut rng = Rng(0xD1B5_4A32_D192_ED03);
    for i in 0..400 {
        let alphabet = [2, 19, 30, 286, 288][i % 5];
        let lengths = random_complete_lengths(&mut rng, alphabet);
        let t = HuffmanTable::from_lengths(&lengths, Completeness::Complete).unwrap();
        let bytes = random_bytes(&mut rng, 64);
        for start in 0..8 {
            // A complete code decodes any bits; only the end can stop it.
            let (_, e) = agree_from(&t, &bytes, start);
            assert_eq!(e, Error::UnexpectedEof);
        }
    }
}

#[test]
fn random_bits_under_fixed_codes() {
    let mut rng = Rng(42);
    for t in [fixed_litlen(), fixed_dist()] {
        for _ in 0..200 {
            let bytes = random_bytes(&mut rng, 48);
            for start in 0..8 {
                assert_eq!(agree_from(&t, &bytes, start).1, Error::UnexpectedEof);
            }
        }
    }
}

#[test]
fn encoded_streams_decode_identically() {
    // Random bits favour short codes; encoding chosen symbols exercises the
    // 13 to 15 bit fallback as often as the hits.
    let mut rng = Rng(0xA076_1D64_78BD_642F);
    for i in 0..300 {
        let lengths = if i % 10 == 0 {
            fixed_lit_lengths()
        } else {
            random_complete_lengths(&mut rng, 288)
        };
        let t = HuffmanTable::from_lengths(&lengths, Completeness::Complete).unwrap();
        let used: Vec<usize> = (0..lengths.len()).filter(|&s| lengths[s] != 0).collect();
        let syms: Vec<usize> = (0..200).map(|_| used[rng.below(used.len())]).collect();
        let bytes = pack(&encode_bits(&lengths, &syms));
        let (n, _) = agree_from(&t, &bytes, 0);
        assert!(n >= syms.len(), "decoded {n} of {}", syms.len());
    }
}

#[test]
fn degenerate_distance_codes_at_every_position() {
    // Invalid codes stop a decode, so restart from every bit position.
    let mut rng = Rng(3);
    for lengths in degenerate_codes() {
        let t = HuffmanTable::from_lengths(&lengths, Completeness::AllowDegenerate).unwrap();
        for bytes in [vec![0u8; 6], vec![0xff; 6], random_bytes(&mut rng, 6)] {
            for start in 0..bytes.len() * 8 {
                agree_from(&t, &bytes, start);
            }
        }
    }
}

#[test]
fn streams_ending_mid_symbol_at_every_truncation_point() {
    // Drop 0 to 16 bits off the end of an encoded stream. A byte-based
    // reader cannot end mid-byte, so pad the *front* with junk bits and
    // start after them, which puts the end at exactly the cut.
    let mut rng = Rng(0x5851_F42D_4C95_7F2D);
    let mut codes: Vec<(Vec<u8>, Completeness)> = vec![
        (fixed_lit_lengths(), Completeness::Complete),
        (vec![5u8; 32], Completeness::Complete),
    ];
    for _ in 0..60 {
        codes.push((
            random_complete_lengths(&mut rng, 288),
            Completeness::Complete,
        ));
        codes.push((
            random_complete_lengths(&mut rng, 30),
            Completeness::Complete,
        ));
    }
    for l in degenerate_codes()
        .into_iter()
        .filter(|l| l.iter().any(|&x| x != 0))
    {
        codes.push((l, Completeness::AllowDegenerate));
    }
    for (lengths, c) in codes {
        let t = HuffmanTable::from_lengths(&lengths, c).unwrap();
        let used: Vec<usize> = (0..lengths.len()).filter(|&s| lengths[s] != 0).collect();
        // Prefer the longest codes for the last symbol, so the cut lands
        // inside a code that would otherwise be a hit or a fallback.
        let mut syms: Vec<usize> = (0..20).map(|_| used[rng.below(used.len())]).collect();
        let longest = *used.iter().max_by_key(|&&s| lengths[s]).unwrap();
        syms.push(longest);
        syms.push(used[rng.below(used.len())]);
        let bits = encode_bits(&lengths, &syms);
        for cut in 0..=16.min(bits.len()) {
            let kept = bits.len() - cut;
            let pad = (8 - kept % 8) % 8;
            let mut stream: Vec<u8> = (0..pad).map(|_| rng.next() as u8 & 1).collect();
            stream.extend_from_slice(&bits[..kept]);
            let bytes = pack(&stream);
            assert_eq!(bytes.len() * 8, pad + kept);
            let (_, e) = agree_from(&t, &bytes, pad);
            if cut > 0 && c == Completeness::Complete {
                // Every whole symbol decodes; the cut one is EOF.
                assert_eq!(e, Error::UnexpectedEof, "cut {cut}");
            }
        }
    }
}

#[test]
fn peek_is_read_without_moving() {
    let mut rng = Rng(11);
    let bytes = random_bytes(&mut rng, 8);
    for start in 0..bytes.len() * 8 {
        let mut r = reader_at(&bytes, start);
        let pos = r.bit_pos();
        let peeked = r.peek_bits(TABLE_BITS);
        assert_eq!(r.bit_pos(), pos);
        let read = r.read_bits(TABLE_BITS);
        assert_eq!(peeked, read, "start {start}");
        if read.is_err() {
            // Lean `readBits_eof`: no peek when fewer than 9 bits remain.
            assert!(pos + TABLE_BITS as usize > r.bit_len());
            assert_eq!(peeked, Err(Error::UnexpectedEof));
        }
    }
}
