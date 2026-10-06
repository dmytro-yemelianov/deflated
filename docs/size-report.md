# Binary size report

Raw data: `scripts/reports/size.json`. Regenerate with `make size`.
`scripts/check_size_report.sh` fails if any number below is absent from that
file — the lesson of maked's "benchmark that lied" is that a number in prose
outlives the measurement that produced it.

No byte target was set before measuring (spec §17 M8).

## Environment

| | |
| --- | --- |
| Host triple | aarch64-apple-darwin |
| rustc | rustc 1.88.0 (6b00bc388 2025-06-23) |
| OS | Darwin 27.2.0 arm64 |
| size tool | /Library/Developer/CommandLineTools/usr/bin/llvm-size |

## Results

| Profile | Total file | `.text` |
| --- | ---: | ---: |
| `release` | 503360 | 278692 |
| `min` | 319488 | 222340 |

These figures include the dynamic-Huffman encoder (`deflate`, M7b), which `vdeflate -c` links; the M7a baseline, in git history, had fixed-Huffman blocks only. The `min` total file moved by far less than its `.text` did; section padding is the likely reason and was not investigated. `scripts/reports/size.json` is the current measurement.

**The total file size is the first column.** `.text` is one section of it and
is never the number to quote (spec §15).

## Working memory

Decoding `big.deflate` (4390 bytes compressed, 1048576 decompressed) with
`--limit 16777216`: peak RSS 3014656 bytes.

## External runtime assumptions

`vdeflate` links the Rust standard library and the platform libc. `deflate-core`
itself is `no_std` and allocates only through `alloc`. A freestanding build of
the core is possible and unmeasured.

## What is not in this report

No comparison against another DEFLATE implementation's binary size. Such a
comparison is only meaningful with matched feature sets, profiles and
link-time settings, and producing one fairly is its own piece of work
(spec §19.12: measure before claiming).
