use deflate_core::{Error, inflate};

#[test]
fn empty_fixed_block_yields_nothing() {
    // Review Focus 2: BFINAL=1, BTYPE=01, then the 7-bit end-of-block code
    // (0000000). Bits LSB-first: 1,1,0, then seven 0s -> 0b0000_0011 = 0x03,
    // with the remaining bits in a second byte.
    assert_eq!(inflate(&[0x03, 0x00]).unwrap(), b"");
}

#[test]
fn fixed_block_with_literals() {
    // zlib: zlib.compressobj(9, zlib.DEFLATED, -15) on b"abc"
    let s = [0x4b, 0x4c, 0x4a, 0x06, 0x00];
    assert_eq!(inflate(&s).unwrap(), b"abc");
}

#[test]
fn fixed_block_with_a_back_reference() {
    // zlib on b"abcabcabcabc"
    let s = [0x4b, 0x4c, 0x4a, 0x4e, 0x84, 0x21, 0x00];
    let out = inflate(&s).unwrap();
    assert_eq!(out, b"abcabcabcabc");
}

#[test]
fn fixed_block_truncated_mid_code_is_eof() {
    assert_eq!(inflate(&[0x03]), Err(Error::UnexpectedEof));
}

#[test]
fn fixed_block_without_end_of_block_is_eof() {
    // Literals and then the stream stops: no 256 symbol is ever read.
    assert_eq!(inflate(&[0x4b, 0x4c, 0x4a]), Err(Error::UnexpectedEof));
}
