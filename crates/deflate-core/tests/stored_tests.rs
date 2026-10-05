use deflate_core::{Error, inflate};

/// One final stored block carrying `payload`.
fn stored_stream(payload: &[u8]) -> Vec<u8> {
    let mut v = vec![0x01]; // BFINAL=1, BTYPE=00, then 5 padding bits
    let len = payload.len() as u16;
    v.extend_from_slice(&len.to_le_bytes());
    v.extend_from_slice(&(!len).to_le_bytes());
    v.extend_from_slice(payload);
    v
}

#[test]
fn decodes_a_stored_block() {
    let s = stored_stream(b"hello");
    assert_eq!(inflate(&s).unwrap(), b"hello");
}

#[test]
fn decodes_multiple_stored_blocks() {
    let mut s = vec![0x00]; // BFINAL=0, BTYPE=00
    s.extend_from_slice(&3u16.to_le_bytes());
    s.extend_from_slice(&(!3u16).to_le_bytes());
    s.extend_from_slice(b"abc");
    s.extend_from_slice(&stored_stream(b"def"));
    assert_eq!(inflate(&s).unwrap(), b"abcdef");
}

// --- Review Focus 2: legal but empty blocks ---

#[test]
fn stored_block_with_zero_length_is_valid_and_yields_nothing() {
    let s = stored_stream(b"");
    assert_eq!(inflate(&s).unwrap(), b"");
}

#[test]
fn zero_length_stored_block_followed_by_data() {
    let mut s = vec![0x00]; // non-final, empty
    s.extend_from_slice(&0u16.to_le_bytes());
    s.extend_from_slice(&(!0u16).to_le_bytes());
    s.extend_from_slice(&stored_stream(b"x"));
    assert_eq!(inflate(&s).unwrap(), b"x");
}

// --- malformed ---

#[test]
fn bad_length_complement_is_rejected() {
    let mut s = stored_stream(b"hi");
    s[3] ^= 0xFF; // corrupt NLEN
    assert_eq!(inflate(&s), Err(Error::InvalidStoredLength));
}

#[test]
fn reserved_block_type_is_rejected() {
    // BFINAL=1, BTYPE=11 -> 0b111 = 0x07
    assert_eq!(inflate(&[0x07]), Err(Error::InvalidBlockType));
}

#[test]
fn truncated_payload_is_eof() {
    let mut s = stored_stream(b"hello");
    s.truncate(s.len() - 2);
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn truncated_before_nlen_is_eof() {
    let mut s = stored_stream(b"hello");
    s.truncate(3);
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn empty_input_is_eof() {
    assert_eq!(inflate(&[]), Err(Error::UnexpectedEof));
}

#[test]
fn stream_without_a_final_block_is_eof() {
    let mut s = vec![0x00];
    s.extend_from_slice(&1u16.to_le_bytes());
    s.extend_from_slice(&(!1u16).to_le_bytes());
    s.push(b'z');
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn trailing_bytes_after_the_final_block_are_ignored() {
    let mut s = stored_stream(b"ok");
    s.extend_from_slice(b"GARBAGE");
    assert_eq!(inflate(&s).unwrap(), b"ok");
}

#[test]
fn decodes_zlib_level0_stored_vector() {
    let deflate = include_bytes!("../../../tests/vectors/stored_level0.deflate");
    let raw = include_bytes!("../../../tests/vectors/stored_level0.raw");
    assert_eq!(inflate(deflate).unwrap(), raw);
}
