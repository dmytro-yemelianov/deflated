# deflate-accel

Optional accelerated entry points layered over `deflate-core`. The core remains
`no_std`, dependency-free, and `unsafe`-free. This crate currently uses
`crc32fast` for GZIP payload CRC-32 and delegates DEFLATE decoding to the core.

```rust
use deflate_accel::Decompressor;

fn decompress(gzip_bytes: &[u8]) -> Result<Vec<u8>, deflate_accel::Error> {
    let mut decoder = Decompressor::new();
    let mut output = Vec::new();
    decoder.gunzip_into(gzip_bytes, &mut output, 64 * 1024 * 1024)?;
    Ok(output)
}
```

Use this crate when the target binary accepts the extra runtime dependency.
Applications that need a dependency-free build can keep using `deflate-core`.
Both paths validate GZIP member checksums and sizes; the adapter changes only
the CRC-32 implementation.
