#![no_main]
use deflate_core::{Decompressor, gunzip_into, inflate_into};
use libfuzzer_sys::fuzz_target;
use std::cell::RefCell;

thread_local! {
    static DECODER: RefCell<Decompressor> = RefCell::new(Decompressor::new());
}

fuzz_target!(|data: &[u8]| {
    let Some((&flags, packet)) = data.split_first() else {
        return;
    };
    DECODER.with(|cell| {
        let mut decoder = cell.borrow_mut();
        if flags & 2 != 0 {
            decoder.release_buffers();
        }
        let limit = if flags & 4 == 0 {
            65536
        } else {
            usize::from(flags)
        };
        let mut output = vec![42; 128];
        let mut expected = vec![99; 64];
        if flags & 1 == 0 {
            assert_eq!(
                decoder.inflate_into(packet, &mut output, limit),
                inflate_into(packet, &mut expected, limit)
            );
        } else {
            assert_eq!(
                decoder.gunzip_into(packet, &mut output, limit),
                gunzip_into(packet, &mut expected, limit)
            );
        }
        assert_eq!(output, expected);
    });
});
