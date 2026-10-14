# GZIP CRC accelerator v11

The Go runtime GZIP profile attributed 24.5% of core samples to portable CRC
work. This iteration adds a checksum hook to the reusable core decoder and an
optional `deflate-accel` crate that supplies `crc32fast`. `deflate-core` keeps
its zero-dependency, `no_std`, `forbid(unsafe_code)` contract and portable CRC
as the default. The accelerated crate also keeps raw decoding on the same core
path.

The hook is `Decompressor::gunzip_into_with_crc32`; callers must supply a
function returning the finalized RFC 1952 CRC-32/ISO-HDLC value. The optional
adapter exposes its own reusable `Decompressor` and selects `crc32fast` there.
GZIP header checksums continue to use the core path because they cover small
headers. No checksum behavior or error handling changed.

## CRC microbenchmark

Seven alternating samples compare `Crc32::compute` with `crc32fast::hash` on
the same Apple M5 and same fixed input bytes. Each sample processes about 8 MiB
per backend (with a minimum of 30 calls). Median throughput:

| Buffer | Portable core | `crc32fast` | Ratio |
|---:|---:|---:|---:|
| 11 B | 5086 MB/s | 4147 MB/s | 0.82x |
| 64 B | 5146 MB/s | 21845 MB/s | 4.25x |
| 1 KiB | 4560 MB/s | 12810 MB/s | 2.81x |
| 8 KiB | 4296 MB/s | 16917 MB/s | 3.94x |
| 64 KiB | 4275 MB/s | 29451 MB/s | 6.89x |
| 256 KiB | 4217 MB/s | 32368 MB/s | 7.68x |
| 1 MiB | 4144 MB/s | 32851 MB/s | 7.93x |

The short-input row is slower with `crc32fast`, so a caller that only hashes
tiny inputs should continue using the default portable path.

## Reused decoder comparison

The paired run compares the accelerated adapter with the current portable core
build and pinned zlib-ng 2.3.3/libdeflate 1.26 workers. It uses four pinned
real inputs (`go`, `inter`, `otel`, `vega-weather`), three encoder lineages,
level 6, raw and GZIP framing, five rotated serial sessions and a 250 ms minimum
per timed sample. The receipt contains 480 timed rows plus exact-output,
truncation, suffix, wrong-size and corrupted-CRC checks. It is a small diagnostic
pool, not independent holdout data or a release benchmark.

| Frame | Portable core | Accelerated | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| Raw | 644.0 MB/s | 694.7 MB/s | 654.7 MB/s | 981.1 MB/s |
| GZIP | 552.2 MB/s | 687.4 MB/s | 628.2 MB/s | 984.2 MB/s |

For GZIP, the adapter is 24.5% faster than the current core and 9.4% faster than
zlib-ng in this pool; libdeflate is still 43.3% faster than the adapter. Raw
decoding has no checksum acceleration. Its result serves as a control and must
not be read as a demonstrated raw-decoder improvement. Per-file timing spread
remains material. The benchmark worker grows by 17,376 bytes (about 3.2%); this
is the decoder example binary, not a measurement of a published library's
linked-size delta.

The reproducible source is [`crc32_probe.rs`](../crates/deflate-accel/examples/crc32_probe.rs).
The full benchmark receipt records the packet, source, native-library and
binary hashes in
[`library-decode-v11-crc-accelerator.json.gz`](../scripts/reports/library-decode-v11-crc-accelerator.json.gz).
The separate run against the frozen v10 worker is retained under
`target/library-v11/real-reuse-5x/` for comparison; the published table above
uses the rebuilt portable core.

Recreate the measured binaries and run from the repository root with the pinned
reference workers present:

```sh
cargo build --locked --release -p deflate-accel --examples
CARGO_TARGET_DIR=target/library-v11/core cargo build --locked --release -p deflate-core --example library_decode_reuse
cargo run --locked --release -p deflate-accel --example crc32_probe > target/library-v11/crc32-probe.csv
python3 scripts/library_bench.py measure --workers target/library-v5/workers-final \
  --candidate target/release/examples/library_decode_reuse_accel \
  --baseline target/library-v11/core/release/examples/library_decode_reuse \
  --reuse --out target/library-v11/real-reuse-current-core \
  --corpus-manifest target/library-v11/real-corpus.json \
  --levels 6 --sessions 5 --minimum-ns 250000000 \
  --study crc32fast-accelerated-backend-current-core
python3 scripts/archive_crc_accelerator.py
```

## Validation

`cargo check -p deflate-accel --examples`,
`cargo clippy -p deflate-accel --lib --examples -- -D warnings`, and
`cargo fmt --all -- --check` pass. No Rust tests were run in this iteration.
