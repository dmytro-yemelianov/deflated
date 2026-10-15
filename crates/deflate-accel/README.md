# deflate-accel

Optional accelerated entry points layered over `deflate-core`. The core remains
`no_std`, dependency-free, and `unsafe`-free. This crate currently uses
`crc32fast` for GZIP payload CRC-32. On x86-64 CPUs with BMI1, BMI2, LZCNT and
POPCNT it also runs the unchanged core decoder compiled with those
instructions; other CPUs and architectures use the ordinary build.

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

## `unsafe` boundary

`deflate-core` forbids `unsafe`. This crate has exactly two `unsafe` blocks,
both in `src/lib.rs` on x86-64: calls to the `#[target_feature]` decoder
wrappers in the private `x86` module. Calling such a function is `unsafe`
only because the CPU must support the enabled features; each call is guarded
by `is_x86_feature_detected!` for every enabled feature. The wrappers contain
no `unsafe` operations: they call the same safe `deflate-core` code, which is
force-inlined so the hot loop is compiled with the wrappers' features. The
crate denies `unsafe_op_in_unsafe_fn`. Results, errors and output contents are
identical to `deflate-core`; the equivalence tests and the `accel_gunzip`
fuzz target compare them.
