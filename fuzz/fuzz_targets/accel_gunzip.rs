#![no_main]
use libfuzzer_sys::fuzz_target;
use std::cell::RefCell;

thread_local! {
    static DECODER: RefCell<deflate_accel::Decompressor> =
        RefCell::new(deflate_accel::Decompressor::new());
}

// The accelerated backends (CRC, and the BMI2 decode path on x86-64) must not
// change any observable raw or gzip result.
fuzz_target!(|data: &[u8]| {
    let Some((&flags, packet)) = data.split_first() else {
        return;
    };
    let limit = if flags & 4 == 0 { 65536 } else { usize::from(flags) };
    // Bit 3 compresses the input first so valid streams reach the bulk loop.
    let compressed;
    let packet = if flags & 8 != 0 {
        compressed = if flags & 1 == 0 {
            deflate_core::deflate(packet)
        } else {
            deflate_core::gzip::gzip(packet, 0).unwrap()
        };
        &compressed[..]
    } else {
        packet
    };
    DECODER.with(|cell| {
        let mut decoder = cell.borrow_mut();
        if flags & 2 != 0 {
            decoder.release_buffers();
        }
        let mut output = vec![42; 128];
        let mut expected = vec![99; 64];
        if flags & 1 == 0 {
            assert_eq!(
                decoder.inflate_into(packet, &mut output, limit),
                deflate_core::inflate_into(packet, &mut expected, limit)
            );
        } else {
            assert_eq!(
                decoder.gunzip_into(packet, &mut output, limit),
                deflate_core::gunzip_into(packet, &mut expected, limit)
            );
        }
        assert_eq!(output, expected);
    });
});
