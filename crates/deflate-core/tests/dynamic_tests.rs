use deflate_core::{Error, inflate, inflate_with_limit};

/// Streams produced by zlib at a level that chooses dynamic blocks. Generated
/// once by `python3 -c` and committed here so the test needs no toolchain.
/// Regenerate with the snippet in Step 5 if they ever need to change.
const DYN_HELLO: &[u8] = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
const DYN_HELLO_RAW: &[u8] = include_bytes!("../../../tests/vectors/dynamic_hello.raw");

#[test]
fn decodes_a_dynamic_block() {
    assert_eq!(inflate(DYN_HELLO).unwrap(), DYN_HELLO_RAW);
}

#[test]
fn dynamic_header_truncated_at_every_prefix_is_eof_or_tree_error() {
    for cut in 1..DYN_HELLO.len().min(40) {
        let r = inflate(&DYN_HELLO[..cut]);
        assert!(
            matches!(
                r,
                Err(Error::UnexpectedEof)
                    | Err(Error::InvalidHuffmanTree)
                    | Err(Error::InvalidCode)
                    | Err(Error::InvalidDistance)
                    | Err(Error::InvalidLength)
            ),
            "cut {cut} gave {r:?}"
        );
    }
}

#[test]
fn hlit_above_286_is_rejected() {
    // BFINAL=1 BTYPE=10, then HLIT = 30 (-> 287 codes).
    // Bits LSB-first: 1,0,1 then HLIT 5 bits = 30 = 0,1,1,1,1
    let mut bits: Vec<u8> = vec![1, 0, 1, 0, 1, 1, 1, 1];
    bits.extend([0u8; 32]); // HDIST, HCLEN, padding
    let mut bytes = vec![0u8; bits.len().div_ceil(8)];
    for (i, b) in bits.iter().enumerate() {
        bytes[i / 8] |= b << (i % 8);
    }
    assert_eq!(inflate(&bytes), Err(Error::InvalidHuffmanTree));
}

// --- Review Focus 3, in a real stream ---

#[test]
fn block_with_no_back_references_has_a_degenerate_distance_tree() {
    // Highly varied short input: zlib emits a dynamic block whose distance
    // code has zero or one symbol. ADR 0004 says we accept it.
    let raw: Vec<u8> = (0u8..=255).collect();
    let stream = include_bytes!("../../../tests/vectors/dynamic_nodist.deflate");
    assert_eq!(inflate(stream).unwrap(), raw);
}

// --- limits ---

#[test]
fn output_limit_is_enforced_on_dynamic_blocks() {
    assert_eq!(
        inflate_with_limit(DYN_HELLO, 1),
        Err(Error::OutputLimitExceeded)
    );
}
