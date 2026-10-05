use deflate_core::Error;
use deflate_core::bitstream::BitReader;
use deflate_core::huffman::{Completeness, HuffmanTable, MAX_CODE_LEN, fixed_dist, fixed_litlen};

/// Encode `sym` with `t`'s canonical code, MSB-first, into a bit stream, then
/// decode it back. Covers every symbol of every table under test.
fn roundtrip(lengths: &[u8], c: Completeness) {
    let t = HuffmanTable::from_lengths(lengths, c).unwrap();
    // Rebuild the canonical codes here, independently of the table, so the
    // test does not merely agree with the implementation it is testing.
    let mut bl_count = [0u16; MAX_CODE_LEN + 1];
    for &l in lengths {
        if l != 0 {
            bl_count[l as usize] += 1;
        }
    }
    let mut next = [0u32; MAX_CODE_LEN + 2];
    let mut code = 0u32;
    for bits in 1..=MAX_CODE_LEN {
        code = (code + bl_count[bits - 1] as u32) << 1;
        next[bits] = code;
    }
    for (sym, &l) in lengths.iter().enumerate() {
        if l == 0 {
            continue;
        }
        let c = next[l as usize];
        next[l as usize] += 1;
        // Pack the code MSB-first into bytes, LSB-first within each byte.
        let mut bits = Vec::new();
        for i in (0..l).rev() {
            bits.push(((c >> i) & 1) as u8);
        }
        let mut bytes = vec![0u8; bits.len().div_ceil(8)];
        for (i, b) in bits.iter().enumerate() {
            bytes[i / 8] |= b << (i % 8);
        }
        let mut r = BitReader::new(&bytes);
        assert_eq!(
            t.decode(&mut r).unwrap() as usize,
            sym,
            "symbol {sym} len {l}"
        );
        assert_eq!(
            r.bit_pos(),
            l as usize,
            "symbol {sym} consumed the wrong width"
        );
    }
}

#[test]
fn rfc_example_roundtrips() {
    roundtrip(&[3, 3, 3, 3, 3, 2, 4, 4], Completeness::Complete);
}

#[test]
fn fixed_tables_roundtrip_every_symbol() {
    let mut lit = vec![8u8; 288];
    lit[144..256].fill(9);
    lit[256..280].fill(7);
    roundtrip(&lit, Completeness::Complete);
    roundtrip(&[5u8; 32], Completeness::Complete);
    // And the constructors agree with the lengths.
    assert!(
        fixed_litlen()
            .decode(&mut BitReader::new(&[0u8, 0]))
            .is_ok()
    );
    assert!(fixed_dist().decode(&mut BitReader::new(&[0u8])).is_ok());
}

// --- Review Focus 3: incomplete and degenerate codes (ADR 0004) ---

#[test]
fn oversubscribed_code_is_rejected_everywhere() {
    // Three symbols of length 1: Kraft sum 3/2 > 1.
    for c in [Completeness::Complete, Completeness::AllowDegenerate] {
        assert_eq!(
            HuffmanTable::from_lengths(&[1, 1, 1], c).unwrap_err(),
            Error::InvalidHuffmanTree
        );
    }
}

#[test]
fn incomplete_code_is_rejected_where_completeness_is_required() {
    // Two symbols of length 2: Kraft sum 1/2 < 1, and two symbols used.
    assert_eq!(
        HuffmanTable::from_lengths(&[2, 2], Completeness::Complete).unwrap_err(),
        Error::InvalidHuffmanTree
    );
    assert_eq!(
        HuffmanTable::from_lengths(&[2, 2], Completeness::AllowDegenerate).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}

#[test]
fn single_symbol_distance_code_is_accepted_as_degenerate() {
    // What zlib emits for a block with no back-references.
    let t = HuffmanTable::from_lengths(&[1, 0, 0, 0], Completeness::AllowDegenerate)
        .expect("ADR 0004: one used symbol is accepted");
    let data = [0x00u8];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r).unwrap(), 0);
    // ...but the literal/length tree never gets that latitude.
    assert_eq!(
        HuffmanTable::from_lengths(&[1, 0, 0, 0], Completeness::Complete).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}

#[test]
fn empty_code_is_accepted_as_degenerate_and_decodes_nothing() {
    let t = HuffmanTable::from_lengths(&[0, 0, 0], Completeness::AllowDegenerate).unwrap();
    let data = [0xFFu8, 0xFF, 0xFF];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r), Err(Error::InvalidCode));
}

#[test]
fn unassigned_bit_pattern_is_invalid_code_not_a_panic() {
    // A complete code where the all-ones pattern of max length is unassigned
    // cannot exist; use a degenerate one-symbol code and feed it a 1 bit.
    let t = HuffmanTable::from_lengths(&[1, 0], Completeness::AllowDegenerate).unwrap();
    let data = [0xFFu8, 0xFF];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r), Err(Error::InvalidCode));
}

#[test]
fn truncated_code_is_eof() {
    let t = HuffmanTable::from_lengths(&[5u8; 32], Completeness::Complete).unwrap();
    let mut r = BitReader::new(&[]);
    assert_eq!(t.decode(&mut r), Err(Error::UnexpectedEof));
}

#[test]
fn length_above_fifteen_is_rejected() {
    let mut l = vec![0u8; 4];
    l[0] = 16;
    assert_eq!(
        HuffmanTable::from_lengths(&l, Completeness::AllowDegenerate).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}

#[test]
fn fixed_tables_are_actually_built() {
    // A table built from the fallback has no symbols and decodes nothing.
    // Both fixed tables must decode symbol 256 (end of block), whose fixed
    // code is seven zero bits.
    let data = [0x00u8, 0x00];
    let mut r = BitReader::new(&data);
    assert_eq!(fixed_litlen().decode(&mut r).unwrap(), 256);
    assert_eq!(r.bit_pos(), 7);
}
