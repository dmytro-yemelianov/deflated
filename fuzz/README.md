# DEFLATE Fuzz Targets

Persistent fuzz targets using `libfuzzer-sys` and `cargo-fuzz`.

## Targets

1. **`inflate`**: Fuzzes the end-to-end decoder `inflate_with_limit` on arbitrary byte streams. Enforces no panic, no hang, and bounded memory allocation.
2. **`dynamic_header`**: Fuzzes `read_dynamic_tables` directly to exercise the dynamic Huffman tree parser in isolation.
3. **`differential`**: In-process differential testing against `miniz_oxide`. Compares output whenever both decoders accept a stream.

4. **`roundtrip`**: `deflate_with_level` output must decode back to the input.
   The first input byte selects Fast, Balanced, or Best, exercising all
   search presets and the size-focused splitter.
5. **`dynamic_lengths`**: `build_lengths` must return a Kraft-valid length set, nonzero exactly where the frequency is, for any frequency vector.

## Running

```bash
cargo +nightly fuzz run inflate        -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run dynamic_header -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run differential   -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run roundtrip      -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run dynamic_lengths -- -max_total_time=60 -rss_limit_mb=4096
```

## Minimized Findings

Any crash or disagreement found by the fuzzer must be minimized with `cargo fuzz tmin` and added permanently to `tests/malformed/` as a regression test case.
