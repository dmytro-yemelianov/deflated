use deflate_core::{Error, deflate_stored, gunzip_into, inflate_into, inflate_with_limit};

#[test]
fn fixed_block_dispatch_boundary_preserves_suffix_limits_and_reuse() {
    let raw = b"hello world";
    let mut writer = deflate_core::bitwriter::BitWriter::new();
    deflate_core::encode_fixed::emit_fixed_block(
        &mut writer,
        true,
        raw.iter()
            .copied()
            .map(deflate_core::tokens::Token::Literal),
    );
    let packet = writer.finish();
    let mut decoder = deflate_core::Decompressor::new();
    let mut out = Vec::new();
    for size in [63, 64, 65, 127] {
        let mut framed = packet.clone();
        framed.resize(size, 0xa5);
        for limit in [0, raw.len() - 1, raw.len(), usize::MAX] {
            for reuse in [false, true] {
                let result = if reuse {
                    decoder.inflate_into(&framed, &mut out, limit)
                } else {
                    inflate_into(&framed, &mut out, limit)
                };
                if limit < raw.len() {
                    assert_eq!(result, Err(Error::OutputLimitExceeded));
                    assert!(out.is_empty());
                } else {
                    let result = result.unwrap();
                    assert_eq!(result.bytes_consumed, packet.len());
                    assert_eq!(result.bytes_written, raw.len());
                    assert_eq!(out, raw);
                }
            }
        }
    }
}

#[test]
fn raw_consumption_and_reuse_across_independent_streams() {
    let mut out = Vec::with_capacity(8192);
    let address = out.as_ptr();
    let inputs = [b"".to_vec(), b"hello".repeat(500), vec![255; 4096]];
    for raw in inputs.iter().chain(inputs.iter().rev()) {
        for mut packet in [
            deflate_stored(raw),
            miniz_oxide::deflate::compress_to_vec(raw, 6),
        ] {
            let consumed = packet.len();
            packet.extend_from_slice(b"container trailer");
            let result = inflate_into(&packet, &mut out, raw.len()).unwrap();
            assert_eq!(result.bytes_consumed, consumed);
            assert_eq!(result.bytes_written, raw.len());
            assert_eq!(&out, raw);
            assert_eq!(out.as_ptr(), address);
        }
    }
}

#[test]
fn failures_clear_partial_output_and_allow_recovery() {
    let raw = b"hello world".repeat(100);
    let packet = miniz_oxide::deflate::compress_to_vec(&raw, 6);
    let mut out = Vec::with_capacity(2048);
    for end in 0..packet.len() {
        out.extend_from_slice(b"old output must not be a dictionary");
        assert!(inflate_into(&packet[..end], &mut out, raw.len()).is_err());
        assert!(out.is_empty());
        assert_eq!(
            inflate_into(&packet, &mut out, raw.len())
                .unwrap()
                .bytes_written,
            raw.len()
        );
        assert_eq!(out, raw);
    }
    assert_eq!(
        inflate_into(&packet, &mut out, raw.len() - 1),
        Err(Error::OutputLimitExceeded)
    );
    assert!(out.is_empty());
    assert_eq!(inflate_with_limit(&packet, raw.len()).unwrap(), raw);
}

#[test]
fn gzip_reuses_output_and_checks_every_member() {
    let a = b"first member".repeat(100);
    let b = b"second member".repeat(100);
    let pa = deflate_core::gzip::gzip(&a, 0).unwrap();
    let pb = deflate_core::gzip::gzip(&b, 0).unwrap();
    let mut out = Vec::with_capacity(4096);
    let address = out.as_ptr();
    for packet in [&pa, &pb, &pa] {
        gunzip_into(packet, &mut out, 4096).unwrap();
        assert_eq!(out.as_ptr(), address);
    }
    let mut joined = pa.clone();
    joined.extend_from_slice(&pb);
    joined.extend_from_slice(&[0; 8]);
    let expected = [a.as_slice(), b.as_slice()].concat();
    assert_eq!(
        gunzip_into(&joined, &mut out, expected.len()).unwrap(),
        expected.len()
    );
    assert_eq!(out, expected);
    assert_eq!(
        gunzip_into(&joined, &mut out, expected.len() - 1),
        Err(Error::OutputLimitExceeded)
    );
    assert!(out.is_empty());
    // CRC corruption in the second member must discard the first member too.
    joined[pa.len() + pb.len() - 8] ^= 1;
    assert!(gunzip_into(&joined, &mut out, 4096).is_err());
    assert!(out.is_empty());
    gunzip_into(&pa, &mut out, 4096).unwrap();
    assert_eq!(out, a);
}

#[test]
fn gzip_errors_do_not_expose_partial_output() {
    let raw = b"test output".repeat(10);
    let packet = deflate_core::gzip::gzip(&raw, 0).unwrap();
    let mut out = Vec::with_capacity(1024);
    for end in 0..packet.len() {
        out.extend_from_slice(b"old");
        assert!(gunzip_into(&packet[..end], &mut out, 1024).is_err());
        assert!(out.is_empty());
    }
    let mut bad = packet.clone();
    bad.push(1);
    assert!(gunzip_into(&bad, &mut out, 1024).is_err());
    assert!(out.is_empty());
}

#[test]
fn errors_integrate_with_rust_error_chains() {
    fn decode() -> Result<(), Box<dyn std::error::Error>> {
        inflate_into(&[], &mut Vec::new(), 0)?;
        Ok(())
    }
    let error = decode().unwrap_err();
    assert_eq!(error.downcast_ref::<Error>(), Some(&Error::UnexpectedEof));
    assert!(!error.to_string().is_empty());
}
