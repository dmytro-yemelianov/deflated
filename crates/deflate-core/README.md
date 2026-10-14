# deflate-core

Whole-buffer raw DEFLATE and GZIP compression/decompression in Rust. The core
uses `no_std` + `alloc`, has no runtime dependencies and forbids unsafe code.
Rust 1.88 or later is required. Version 0.1 is under active development; the
current focus is decompression speed and reusable buffer APIs.

```rust
use deflate_core::{deflate, inflate_into, Error};

fn round_trip() -> Result<(), Error> {
    let packet = deflate(b"hello world");
    let mut output = Vec::with_capacity(64 * 1024);
    let decoded = inflate_into(&packet, &mut output, 64 * 1024)?;
    assert_eq!(decoded.bytes_consumed, packet.len());
    assert_eq!(decoded.bytes_written, 11);
    assert_eq!(output, b"hello world");
    // Reuse output for the next independent stream.
    Ok(())
}
```

| API | Behavior |
| --- | --- |
| `inflate(input)` | Returns a new buffer, with the default 1 GiB output limit |
| `inflate_with_limit(input, limit)` | Returns a new buffer with an explicit limit |
| `inflate_into(input, &mut output, limit)` | Reuses storage; returns consumed/written byte counts |
| `gunzip(input, limit)` | Returns all validated gzip members in a new buffer |
| `gunzip_into(input, &mut output, limit)` | Reuses storage; returns decoded length |
| `Decompressor::inflate_into` / `Decompressor::gunzip_into` | Reuses working tables and caller output across independent streams |
| `Decompressor::gunzip_into_with_crc32` | Same gzip path with a caller-supplied CRC-32/ISO-HDLC function |
| `Decompressor::release_buffers()` | Frees retained working buffers; caller output is unaffected |
| `deflate(input)` / `deflate_with_level(input, level)` | Raw DEFLATE compression |
| `gzip::gzip(input, limit)` | GZIP compression; legacy limit argument is not used for encoding |

The `*_into` APIs clear previous contents; they never use those contents as a
dictionary. Output is empty after an error, and can be reused for another call.
Limits bound decoded length, not allocator capacity. Existing capacity may be
larger than the chosen limit; storage can grow as decoding requires.

Raw DEFLATE stops at the final block and accepts trailing bytes. The consumption
count includes padding in the last byte. Compare it with `input.len()` when the
application requires exact consumption. GZIP validates every header, CRC32 and
ISIZE, accepts concatenated members and final zero padding, and rejects other
trailing bytes. The output limit is cumulative across members.

`Error` implements `Display` and the Rust error trait. These are whole-buffer
APIs, with no incremental streaming, preset dictionary or zlib-wrapper API.
GZIP format errors currently share error variants with the raw decoder.

For an accelerated GZIP checksum while keeping this crate dependency-free, see
the optional workspace crate [`deflate-accel`](../deflate-accel/README.md).
Custom checksum functions must return the finalized CRC-32/ISO-HDLC value used
by RFC 1952; the default `gunzip_into` always uses the portable implementation.

The accompanying Lean model proves properties of the model. There is no
formal refinement proof of this Rust library. Correctness evidence comprises
reference tests, differential decoding and fuzzing. Performance comparisons
with zlib-ng/libdeflate are workload-specific; development measurements are
not a general superiority claim.

For repeated decoding, keep a decoder alongside the output buffer:

```rust
use deflate_core::{Decompressor, Error};

fn decode_many(packets: &[&[u8]]) -> Result<(), Error> {
    let mut decoder = Decompressor::new(); // No heap allocation yet.
    let mut output = Vec::new();
    for packet in packets {
        decoder.inflate_into(packet, &mut output, 64 * 1024)?;
        // Consume output here; the next call replaces it.
    }
    decoder.release_buffers();
    Ok(())
}
```

A used dynamic decoder retains about 20 KiB of table storage; gzip can also
retain a member scratch buffer. Every header is decoded and every table rebuilt:
this API reuses allocations, not compressed input or previous output as a
cache/dictionary. Errors leave output empty and do not require a reset before
the next independent call. Memory limits bound decoded length, not retained
capacity; release the buffers or drop the decoder when retention is undesirable.
Gzip optional header fields may still allocate per member. This is not streaming.
