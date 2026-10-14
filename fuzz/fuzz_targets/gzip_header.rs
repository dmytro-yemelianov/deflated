#![no_main]
use deflate_core::{bitstream::BitReader, gunzip, gzip::read_gzip_header, Decompressor};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let mut reader = BitReader::new(data);
    match read_gzip_header(&mut reader) {
        Err(error) => {
            // A header error precedes any payload or trailer error.
            assert_eq!(gunzip(data, 65536), Err(error));
        }
        Ok(_) => {
            // The public metadata parser independently determines the exact
            // boundary. Append an empty fixed block and its zero CRC/ISIZE.
            let mut packet = data[..reader.bit_pos() / 8].to_vec();
            packet.extend_from_slice(&[3, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
            assert_eq!(gunzip(&packet, 0).unwrap(), b"");
            let mut decoder = Decompressor::new();
            let mut out = vec![42; 16];
            assert_eq!(decoder.gunzip_into(&packet, &mut out, 0), Ok(0));
            assert!(out.is_empty());
        }
    }
});
