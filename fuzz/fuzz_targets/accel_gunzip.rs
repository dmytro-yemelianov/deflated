#![no_main]
use libfuzzer_sys::fuzz_target;
use std::cell::RefCell;

thread_local! {
    static DECODER: RefCell<deflate_accel::Decompressor> =
        RefCell::new(deflate_accel::Decompressor::new());
}

// The accelerated CRC backend must not change any observable gzip result.
fuzz_target!(|data: &[u8]| {
    let Some((&flags, packet)) = data.split_first() else {
        return;
    };
    let limit = if flags & 4 == 0 { 65536 } else { usize::from(flags) };
    DECODER.with(|cell| {
        let mut decoder = cell.borrow_mut();
        if flags & 2 != 0 {
            decoder.release_buffers();
        }
        let mut output = vec![42; 128];
        let mut expected = vec![99; 64];
        assert_eq!(
            decoder.gunzip_into(packet, &mut output, limit),
            deflate_core::gunzip_into(packet, &mut expected, limit)
        );
        assert_eq!(output, expected);
    });
});
