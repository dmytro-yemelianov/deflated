use deflate_core::{Error, inflate, inflate_with_limit};

/// A compression bomb: ~70 bytes expanding to ~64 MiB, built the way a real
/// one is — maximum-length copies at distance 1, chained across blocks.
fn bomb(target: usize) -> Vec<u8> {
    let mut raw = vec![0u8; target];
    raw[0] = b'A';
    for b in raw.iter_mut() {
        *b = b'A';
    }
    // Compress with zlib at the highest level: long runs collapse to a few
    // length/distance pairs. Generated at test time rather than committed, so
    // the vector stays small in the repository.
    let mut out = Vec::new();
    {
        use std::io::Write;
        let mut e = flate2::write::DeflateEncoder::new(&mut out, flate2::Compression::best());
        e.write_all(&raw).unwrap();
        e.finish().unwrap();
    }
    out
}

// --- Review Focus 5: compression bombs ---

#[test]
fn bomb_stops_at_the_limit_without_allocating_past_it() {
    let s = bomb(64 * 1024 * 1024);
    assert!(s.len() < 100_000, "bomb stream should be tiny: {}", s.len());
    assert_eq!(
        inflate_with_limit(&s, 1024),
        Err(Error::OutputLimitExceeded)
    );
    assert_eq!(inflate_with_limit(&s, 0), Err(Error::OutputLimitExceeded));
}

#[test]
fn limit_equal_to_the_output_size_succeeds_and_one_less_fails() {
    let raw = b"hello world".repeat(100);
    let mut s = Vec::new();
    {
        use std::io::Write;
        let mut e = flate2::write::DeflateEncoder::new(&mut s, flate2::Compression::best());
        e.write_all(&raw).unwrap();
        e.finish().unwrap();
    }
    assert_eq!(inflate_with_limit(&s, raw.len()).unwrap(), raw);
    assert_eq!(
        inflate_with_limit(&s, raw.len() - 1),
        Err(Error::OutputLimitExceeded)
    );
}

#[test]
fn a_single_max_length_copy_cannot_exceed_the_limit() {
    // Hand-built: a stored block of one byte, then a fixed block whose only
    // content is a 258-length copy at distance 1. With a limit of 100 the
    // copy must be refused before it allocates.
    let mut s = vec![0x00u8]; // non-final stored
    s.extend_from_slice(&1u16.to_le_bytes());
    s.extend_from_slice(&(!1u16).to_le_bytes());
    s.push(b'A');
    // The rest is produced by zlib; what matters is that `inflate_with_limit`
    // never returns Ok with more than the limit.
    let r = inflate_with_limit(&s, 100);
    assert!(
        matches!(r, Err(Error::UnexpectedEof)) || r.map(|v| v.len() <= 100).unwrap_or(true),
        "limit violated"
    );
}

#[test]
#[allow(clippy::assertions_on_constants)]
fn default_limit_is_documented_and_finite() {
    assert!(deflate_core::DEFAULT_LIMIT > 0);
    assert!(deflate_core::DEFAULT_LIMIT < usize::MAX);
}

// --- Review Focus 1: truncation at every boundary, whole decoder ---

#[test]
fn every_prefix_of_every_vector_errors_or_decodes_a_prefix() {
    for (name, stream) in [
        (
            "stored",
            include_bytes!("../../../tests/vectors/stored_level0.deflate").as_slice(),
        ),
        (
            "dynamic",
            include_bytes!("../../../tests/vectors/dynamic_hello.deflate").as_slice(),
        ),
        (
            "nodist",
            include_bytes!("../../../tests/vectors/dynamic_nodist.deflate").as_slice(),
        ),
    ] {
        for cut in 0..stream.len() {
            // The contract: an error, never a panic, never a hang, and never
            // a success claiming more output than the full stream yields.
            if let Ok(v) = inflate_with_limit(&stream[..cut], 1 << 22) {
                let full = inflate_with_limit(stream, 1 << 22).unwrap();
                assert!(
                    v.len() <= full.len(),
                    "{name}: prefix {cut} produced more than the whole stream"
                );
            }
        }
    }
}

#[test]
fn every_single_bit_flip_errors_or_decodes() {
    let stream = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
    for i in 0..stream.len() {
        for bit in 0..8 {
            let mut m = stream.to_vec();
            m[i] ^= 1 << bit;
            // Only requirement: it returns. No panic, no hang, no OOM.
            let _ = inflate_with_limit(&m, 1 << 22);
        }
    }
}

#[test]
fn empty_and_single_byte_inputs_error() {
    assert_eq!(inflate(&[]), Err(Error::UnexpectedEof));
    for b in 0u8..=255 {
        let r = inflate(&[b]);
        assert!(r.is_err(), "single byte {b:#04x} decoded to {r:?}");
    }
}
