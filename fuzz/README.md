# DEFLATE Fuzz Targets

Persistent fuzz targets using `libfuzzer-sys` and `cargo-fuzz`.

## Targets

1. **`inflate`**: Fuzzes the end-to-end decoder `inflate_with_limit` on arbitrary byte streams. Enforces no panic, no hang, and bounded memory allocation.
2. **`dynamic_header`**: Fuzzes `read_dynamic_tables` directly to exercise the dynamic Huffman tree parser in isolation.
3. **`differential`**: In-process differential testing against `miniz_oxide`. Compares output whenever both decoders accept a stream.

4. **`roundtrip`**: compressed output must decode back to the input under
   deflate-core and miniz. The first input byte selects Fast, Balanced, Best
   or a research configuration. Further bytes vary probe budget, lazy mode,
   insertion tail, index and checked block size within validated bounds.
5. **`dynamic_lengths`**: `build_lengths` must return a Kraft-valid length set, nonzero exactly where the frequency is, for any frequency vector.
6. **`structured_decode`**: Exercises the experimental DSC1 frame/operation decoder
   with a 1 MiB output limit on arbitrary input bytes.
7. **`structured_roundtrip`**: Requires byte-exact DSC1 encode/decode recovery
   across the research settings, with bounded input length.

DSC1 remains a rejected research prototype after the
[campaign closure](../docs/new-methods-report.md). Its fuzz targets preserve
finite regression evidence and do not establish formal verification or promotion.

## Running

```bash
cargo +nightly fuzz run inflate        -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run dynamic_header -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run differential   -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run roundtrip      -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run dynamic_lengths -- -max_total_time=60 -rss_limit_mb=4096
python3 scripts/structured_fuzz_seeds.py
cargo +nightly fuzz run structured_decode -- -max_total_time=60 -rss_limit_mb=4096
cargo +nightly fuzz run structured_roundtrip -- -max_total_time=60 -max_len=70000 -rss_limit_mb=4096
```

## Minimized Findings

Any crash or disagreement found by the fuzzer must be minimized with `cargo fuzz tmin` and added permanently to `tests/malformed/` as a regression test case.
