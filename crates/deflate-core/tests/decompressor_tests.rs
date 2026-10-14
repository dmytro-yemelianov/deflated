use deflate_core::{Decompressor, deflate_stored, gunzip_into, inflate_into};

#[test]
fn mixed_streams_errors_limits_and_release_match_fresh_calls() {
    let dynamic = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
    let nodist = include_bytes!("../../../tests/vectors/dynamic_nodist.deflate");
    let raw = b"independent payload".repeat(500);
    let gzip = deflate_core::gzip::gzip(&raw, 0).unwrap();
    let empty = deflate_core::gzip::gzip(b"", 0).unwrap();
    let joined = [empty.as_slice(), gzip.as_slice(), gzip.as_slice(), &[0; 4]].concat();
    let mut decoder = Decompressor::new();
    let mut output = Vec::with_capacity(32768);
    let mut expected = Vec::new();
    for round in 0..3 {
        for packet in [
            dynamic.to_vec(),
            nodist.to_vec(),
            deflate_stored(&raw),
            vec![7],
            vec![],
        ] {
            for end in (0..packet.len()).step_by(7).chain([packet.len()]) {
                for limit in [0, 17, 32768] {
                    output.extend_from_slice(b"old output");
                    assert_eq!(
                        decoder.inflate_into(&packet[..end], &mut output, limit),
                        inflate_into(&packet[..end], &mut expected, limit)
                    );
                    assert_eq!(output, expected);
                }
            }
        }
        for packet in [&gzip, &empty, &joined] {
            for end in (0..packet.len()).step_by(7).chain([packet.len()]) {
                for limit in [0, raw.len() - 1, 32768] {
                    assert_eq!(
                        decoder.gunzip_into(&packet[..end], &mut output, limit),
                        gunzip_into(&packet[..end], &mut expected, limit)
                    );
                    assert_eq!(output, expected);
                }
            }
        }
        let mut corrupt = joined.clone();
        corrupt[empty.len() + gzip.len() - 8] ^= 1;
        assert_eq!(
            decoder.gunzip_into(&corrupt, &mut output, 32768),
            gunzip_into(&corrupt, &mut expected, 32768)
        );
        assert!(output.is_empty());
        decoder.gunzip_into(&joined, &mut output, 32768).unwrap();
        assert_eq!(output, raw.repeat(2));
        if round == 1 {
            decoder.release_buffers();
        }
    }
}

#[test]
fn raw_history_does_not_cross_calls_and_suffix_consumption_is_exact() {
    use deflate_core::{Error, bitwriter::BitWriter, tokens::Token};
    let mut decoder = Decompressor::default();
    let mut output = Vec::with_capacity(16384);
    let pointer = output.as_ptr();
    let mut packet = deflate_core::deflate(b"previous history");
    let consumed = packet.len();
    packet.extend_from_slice(b"suffix");
    assert_eq!(
        decoder
            .inflate_into(&packet, &mut output, 16384)
            .unwrap()
            .bytes_consumed,
        consumed
    );
    assert_eq!(output.as_ptr(), pointer);
    let mut writer = BitWriter::new();
    deflate_core::encode_fixed::emit_fixed_block(
        &mut writer,
        true,
        [Token::Match { len: 3, dist: 1 }],
    );
    let bad = writer.finish();
    assert_eq!(
        decoder.inflate_into(&bad, &mut output, 16384),
        Err(Error::InvalidDistance)
    );
    assert!(output.is_empty());
    decoder.inflate_into(&packet, &mut output, 16384).unwrap();
    assert_eq!(output, b"previous history");
    assert_eq!(output.as_ptr(), pointer);
}

#[test]
fn multiple_blocks_and_independent_contexts() {
    use std::io::Write;
    let mut encoder =
        flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::default());
    let mut expected = Vec::new();
    for i in 0..16 {
        let raw = format!(
            "block {i}: {}",
            "tables and history across blocks ".repeat(200)
        );
        encoder.write_all(raw.as_bytes()).unwrap();
        encoder.flush().unwrap();
        expected.extend_from_slice(raw.as_bytes());
    }
    let packet = encoder.finish().unwrap();
    let mut a = Decompressor::new();
    let mut b = Decompressor::new();
    let mut output = Vec::new();
    for _ in 0..3 {
        for decoder in [&mut a, &mut b] {
            decoder
                .inflate_into(&packet, &mut output, expected.len())
                .unwrap();
            assert_eq!(output, expected);
        }
    }
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<Decompressor>();
}
