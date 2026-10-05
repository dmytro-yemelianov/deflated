# Decode performance baseline

Raw data: `scripts/reports/perf.json` (throughput) and
`scripts/reports/profile.json` (where the time goes). `make perf` and, on
macOS with `samply` installed, `make profile` measure into `target/reports/`
and print each input next to this baseline; that is how a candidate
optimization is judged. `bash scripts/perf_report.sh --record` (and the same
for `profile_report.sh`) replaces the baseline and regenerates the tables
below, which are never edited by hand. `scripts/check_perf_report.sh` fails if
any number in this file is absent from the baseline JSON.

This is the baseline spec §16 asks for before any optimization: v1
deliberately made none (plan, "Gaps found and accepted"). Nothing in
`deflate-core` was changed to produce it.

## Method

- **Corpus.** `scripts/perf_corpus.py` writes four seeded 8 MiB payloads
  (synthetic English-like text, random bytes, a 9-byte repeating pattern,
  zeros) and compresses each with zlib into raw streams of dynamic, fixed-only
  and stored-only blocks. Random data is stored-only: zlib emits stored blocks
  for it whatever strategy is asked for.
- **Timing.** `crates/deflate-core/examples/perf.rs` decodes each stream
  in-process, best of 15, with `deflate-core` and with `miniz_oxide` (already a
  dev-dependency, for the differential tests). Both outputs are checked against
  the original payload before anything is timed. In-process matters: the CLI
  spends a few milliseconds on process start and I/O, which is most of a stored
  stream's cost.
- **Profile.** `scripts/profile_report.sh` samples the same example with
  `samply`. All of `deflate-core` inlines into `decode_huff_block`, so a
  function-level profile only says "decode_huff_block". `scripts/profile_attrib.py`
  resolves every sampled address with `atos -i`, which reports the inline
  chain, and counts each sample once per core function on it. Percentages are
  inclusive, so a column can add up to more than the whole.

Environment: Apple M5, `aarch64-apple-darwin`, rustc 1.88.0, `release` profile
(`opt-level = 3`), reference `miniz_oxide` 0.8.9.

## Throughput

"Slowdown" is deflate-core time over miniz_oxide time. MB/s are of
decompressed output (8388608 bytes for every input).

<!-- perf:throughput -->
| Input | Compressed bytes | deflate-core MB/s | miniz_oxide MB/s | Slowdown |
| --- | ---: | ---: | ---: | ---: |
| `random.stored.deflate` | 8389258 | 14171.9 | 34256.7 | 2.42× |
| `repetitive.dyn.deflate` | 16280 | 2194.7 | 3256.8 | 1.48× |
| `repetitive.fixed.deflate` | 60974 | 2088.8 | 3278.0 | 1.57× |
| `repetitive.stored.deflate` | 8389258 | 16258.3 | 36531.8 | 2.25× |
| `text.dyn.deflate` | 3050677 | 237.9 | 498.5 | 2.1× |
| `text.fixed.deflate` | 3854367 | 253.1 | 479.0 | 1.89× |
| `text.stored.deflate` | 8389258 | 16418.7 | 35370.0 | 2.15× |
| `zeros.dyn.deflate` | 8144 | 2796.1 | 7903.2 | 2.83× |
| `zeros.fixed.deflate` | 52840 | 2590.1 | 9643.9 | 3.72× |
| `zeros.stored.deflate` | 8389258 | 15393.1 | 37596.0 | 2.44× |
<!-- /perf:throughput -->

Back-to-back runs on the same machine moved the slowdown by up to about 5% on
Huffman-coded inputs and up to about 15% on stored inputs, which take about
half a millisecond and are bound by memory bandwidth. Treat a smaller change
than that as noise.

## Where the time goes

<!-- perf:profile -->
`text.dyn.deflate` (4016 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 94.1 |
| `huffman::decode` | 52.8 |
| `bitstream::read_bits` | 18.9 |
| `lz77::read_distance` | 18.5 |
| `lz77::copy_back` | 10.8 |
| `bitstream::read_bit` | 9.1 |
| `lz77::{closure#0}` | 2.1 |
| `lz77::read_length` | 1.0 |
| perf (outside deflate-core) | 5.2 |

`zeros.fixed.deflate` (4000 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 95.9 |
| `lz77::copy_back` | 82.6 |
| `huffman::decode` | 8.6 |
| `lz77::{closure#0}` | 0.7 |
| libsystem_kernel.dylib | 2.4 |
| libsystem_platform.dylib | 1.5 |

`repetitive.dyn.deflate` (3980 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 96.8 |
| `lz77::copy_back` | 90.7 |
| `huffman::decode` | 1.3 |
| `lz77::{closure#0}` | 1.2 |
| `bitstream::read_bits` | 0.9 |
| `lz77::read_distance` | 0.7 |
| libsystem_kernel.dylib | 1.6 |
| libsystem_platform.dylib | 1.5 |

`text.stored.deflate` (3987 samples)

| Function | Inclusive % |
| --- | ---: |
| libsystem_platform.dylib | 87.6 |
| libsystem_kernel.dylib | 11.9 |
<!-- /perf:profile -->

## Findings

1. **Huffman symbol decoding is the largest cost on real text.**
   `huffman::decode` reads one bit, compares against one code length, and
   repeats, up to 15 times per symbol, which is about half of all text decode
   time. This is the design `huffman.rs` documents ("No decode table is built,
   which keeps the code small and the correspondence with the model direct").
2. **Extra bits are read one bit at a time.** `bitstream::read_bits` loops over
   `read_bit`, re-checking the bounds and indexing the byte slice per bit.
   Distance extra bits, up to 13 per match, account for most of it on text.
3. **Back-references are copied one byte at a time.** `lz77::copy_back` does a
   checked `get` and a `push` per byte. On streams that are mostly long
   matches (zeros, repetitive) it is over 80% of the time, and that is where the
   ratio to miniz_oxide is worst.
4. **Stored blocks do no work in deflate-core.** The time is all `memmove` and
   kernel page faults from `Vec` growth. The output is never sized ahead, so
   growing it repeatedly reallocates and copies.
5. **Building tables costs nothing measurable.** `from_lengths` and
   `read_dynamic_tables` do not appear in any profile above, even for dynamic
   streams; `profile_attrib.py` drops shares under half a percent.

## Candidates, in order of expected payoff

Each one must still go through spec §16: candidate, then proof or refinement
check, then the test and differential suites, then a new run of this report
and of `make size`, because a lookup table costs binary size.

| # | Candidate | Targets | Effect on the model correspondence |
| --- | --- | --- | --- |
| 1 | Copy non-overlapping matches with `extend_from_within`, and overlapping ones in chunks of `dist` bytes | `lz77::copy_back` | None on semantics. The Lean `copyBack` stays byte-at-a-time; a Rust-side test pins equivalence for every `dist`/`len` |
| 2 | Read multi-bit fields from the byte slice directly, not via `read_bit` | `bitstream::read_bits` | None: same LSB-first value, same all-or-nothing EOF check (P1) |
| 3 | Table-driven Huffman decode with a peeked bit window and the current canonical walk as the fallback for long codes | `huffman::decode` | Changes the decode algorithm. Needs an ADR and a Lean lemma that table lookup equals the canonical decode, or an explicit statement that it is covered by differential testing only |
| 4 | Reserve output capacity for stored blocks, bounded by the limit | stored path | None, but must keep the bomb rule: never reserve past `limit` |

The ordering is by expected payoff per unit of risk to the verification story,
not by raw speedup: 1 and 2 leave the model untouched, while 3 is the largest
win on text and the only one that needs new proof work.

## What is not in this report

No comparison against zlib or zlib-ng, and no Linux or x86 numbers. Absolute
MB/s are specific to this machine. The slowdown column is what a later
optimization should move. The Lean model's speed is not measured: it is a
specification, not a decoder anyone runs.
