use deflate_core::error::Error;
use deflate_core::zip::{CompressionMethod, find_end_central_dir, unzip_single, zip_single};

// Generated and independently read with Python zipfile on a nonseekable BytesIO.
const STREAMED: &[u8] = &[
    80, 75, 3, 4, 20, 0, 8, 0, 8, 0, 39, 166, 70, 93, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10, 0, 0,
    0, 115, 116, 114, 101, 97, 109, 46, 116, 120, 116, 203, 72, 205, 201, 201, 87, 40, 207, 47,
    202, 73, 1, 0, 80, 75, 7, 8, 133, 17, 74, 13, 13, 0, 0, 0, 11, 0, 0, 0, 80, 75, 1, 2, 20, 3,
    20, 0, 8, 0, 8, 0, 39, 166, 70, 93, 133, 17, 74, 13, 13, 0, 0, 0, 11, 0, 0, 0, 10, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 128, 1, 0, 0, 0, 0, 115, 116, 114, 101, 97, 109, 46, 116, 120, 116, 80,
    75, 5, 6, 0, 0, 0, 0, 1, 0, 1, 0, 56, 0, 0, 0, 69, 0, 0, 0, 0, 0,
];

#[test]
fn stored_limit_is_enforced() {
    let archive = zip_single(b"test", b"hello world", CompressionMethod::Stored).unwrap();
    assert_eq!(unzip_single(&archive, 0), Err(Error::OutputLimitExceeded));
    assert_eq!(unzip_single(&archive, 10), Err(Error::OutputLimitExceeded));
    assert_eq!(unzip_single(&archive, 11).unwrap().0, b"hello world");
}

#[test]
fn python_streamed_descriptor() {
    assert_eq!(
        unzip_single(STREAMED, 11).unwrap(),
        (b"hello world".to_vec(), b"stream.txt".to_vec())
    );
    assert_eq!(unzip_single(STREAMED, 10), Err(Error::OutputLimitExceeded));
}

#[test]
fn payload_eocd_signature_is_ignored() {
    let mut payload = b"PK\x05\x06".to_vec();
    payload.extend_from_slice(&[b'x'; 32]);
    let archive = zip_single(b"test", &payload, CompressionMethod::Stored).unwrap();
    assert_eq!(find_end_central_dir(&archive), Some(archive.len() - 22));
    assert_eq!(unzip_single(&archive, payload.len()).unwrap().0, payload);
}

#[test]
fn oversized_filename_is_rejected() {
    assert!(zip_single(&vec![b'x'; 65536], b"", CompressionMethod::Stored).is_err());
    let name = vec![b'x'; 65535];
    let archive = zip_single(&name, b"", CompressionMethod::Stored).unwrap();
    assert_eq!(unzip_single(&archive, 0).unwrap().1, name);
}

#[test]
fn unsigned_descriptor_and_corruption() {
    let cd = STREAMED
        .windows(4)
        .position(|s| s == b"PK\x01\x02")
        .unwrap();
    let descriptor = cd - 16;
    let mut unsigned = STREAMED.to_vec();
    unsigned.drain(descriptor..descriptor + 4);
    let end = unsigned.len() - 22;
    unsigned[end + 16..end + 20].copy_from_slice(&((cd - 4) as u32).to_le_bytes());
    assert_eq!(unzip_single(&unsigned, 11).unwrap().0, b"hello world");
    for offset in [descriptor + 4, descriptor + 8, descriptor + 12] {
        let mut bad = STREAMED.to_vec();
        bad[offset] ^= 1;
        assert!(unzip_single(&bad, 11).is_err());
    }
    let mut truncated = STREAMED.to_vec();
    truncated.remove(cd - 1);
    let end = truncated.len() - 22;
    truncated[end + 16..end + 20].copy_from_slice(&((cd - 1) as u32).to_le_bytes());
    assert!(unzip_single(&truncated, 11).is_err());
}

#[test]
fn eocd_comment_and_bounds_are_checked() {
    let mut archive = zip_single(b"test", b"hello", CompressionMethod::Stored).unwrap();
    let end = archive.len() - 22;
    // A signature inside the comment is not an EOCD record.
    let comment = b"PK\x05\x06xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    archive[end + 20..end + 22].copy_from_slice(&(comment.len() as u16).to_le_bytes());
    archive.extend_from_slice(comment);
    assert_eq!(find_end_central_dir(&archive), Some(end));
    assert_eq!(unzip_single(&archive, 5).unwrap().0, b"hello");
    archive.push(0);
    assert_eq!(find_end_central_dir(&archive), None);
    archive.pop();
    archive[end + 16..end + 20].copy_from_slice(&u32::MAX.to_le_bytes());
    assert_eq!(find_end_central_dir(&archive), None);
}

#[test]
fn forged_sizes_and_header_disagreement_are_rejected() {
    let original = zip_single(b"test", b"hello", CompressionMethod::Stored).unwrap();
    let cd = 34 + 5;
    let mut bad = original.clone();
    bad[cd + 24..cd + 28].copy_from_slice(&100u32.to_le_bytes());
    assert_eq!(unzip_single(&bad, 5), Err(Error::OutputLimitExceeded));
    let mut bad = original.clone();
    bad[cd + 20..cd + 24].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(unzip_single(&bad, 5).is_err());
    let mut bad = original;
    bad[14] ^= 1;
    assert!(unzip_single(&bad, 5).is_err());
}

#[test]
fn python_stored_descriptor() {
    let archive: &[u8] = &[
        80, 75, 3, 4, 20, 0, 8, 0, 0, 0, 83, 166, 70, 93, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10,
        0, 0, 0, 115, 116, 111, 114, 101, 100, 46, 116, 120, 116, 104, 101, 108, 108, 111, 32, 119,
        111, 114, 108, 100, 80, 75, 7, 8, 133, 17, 74, 13, 11, 0, 0, 0, 11, 0, 0, 0, 80, 75, 1, 2,
        20, 3, 20, 0, 8, 0, 0, 0, 83, 166, 70, 93, 133, 17, 74, 13, 11, 0, 0, 0, 11, 0, 0, 0, 10,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 128, 1, 0, 0, 0, 0, 115, 116, 111, 114, 101, 100, 46, 116,
        120, 116, 80, 75, 5, 6, 0, 0, 0, 0, 1, 0, 1, 0, 56, 0, 0, 0, 67, 0, 0, 0, 0, 0,
    ];
    assert_eq!(unzip_single(archive, 11).unwrap().0, b"hello world");
    assert_eq!(unzip_single(archive, 0), Err(Error::OutputLimitExceeded));
}

#[test]
fn deflate_compression_option_flags_are_supported() {
    let cd = STREAMED
        .windows(4)
        .position(|s| s == b"PK\x01\x02")
        .unwrap();
    // Each variant was independently read using Python zipfile.
    for options in [0, 2, 4, 6] {
        let mut archive = STREAMED.to_vec();
        archive[6] |= options;
        archive[cd + 8] |= options;
        assert_eq!(unzip_single(&archive, 11).unwrap().0, b"hello world");
    }
}

#[test]
fn stored_option_bits_and_unsupported_flags_are_rejected() {
    // Bits 1/2 describe DEFLATE compression options and are undefined for Stored.
    let stored = zip_single(b"test", b"hello world", CompressionMethod::Stored).unwrap();
    let cd = find_end_central_dir(&stored).unwrap() - 50;
    for options in [2, 4, 6] {
        let mut archive = stored.clone();
        archive[6] |= options;
        archive[cd + 8] |= options;
        assert_eq!(unzip_single(&archive, 11), Err(Error::InvalidBlockType));
    }
    let cd = STREAMED
        .windows(4)
        .position(|s| s == b"PK\x01\x02")
        .unwrap();
    for unsupported in [1u16, 0x10, 0x40, 0x2000] {
        let mut archive = STREAMED.to_vec();
        let flags = (8 | unsupported).to_le_bytes();
        archive[6..8].copy_from_slice(&flags);
        archive[cd + 8..cd + 10].copy_from_slice(&flags);
        assert_eq!(unzip_single(&archive, 11), Err(Error::InvalidBlockType));
    }
}
