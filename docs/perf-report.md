# Decode performance baseline

Raw data: `scripts/reports/perf.json` (throughput) and
`scripts/reports/profile.json` (where the time goes). `make perf` and, on
macOS with `samply` installed, `make profile` measure into `target/reports/`
and print each input next to this baseline; that is how a candidate
optimization is judged. `bash scripts/perf_report.sh --record` (and the same
for `profile_report.sh`) replaces the baseline and regenerates the tables
below, which are never edited by hand. `scripts/check_perf_report.sh` fails if
any number in this file is absent from the baseline JSON.

This is the baseline the next optimization is judged against (spec §16).

## History

| Baseline | `deflate-core` state |
| --- | --- |
| v1, commit `bcc7d19` | As shipped: no optimization (plan, "Gaps found and accepted") |
| Current | Candidates 1 (`copy_back` in chunks) and 2 (`read_bits` from one byte window) applied |

`git show bcc7d19:scripts/reports/perf.json` has the v1 numbers. Candidates
1 and 2 brought match-heavy inputs to roughly miniz_oxide's speed or better
and cut the text gap by about a sixth. Neither changed the Lean model.

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
| `random.stored.deflate` | 8389258 | 15188.7 | 36190.4 | 2.38× |
| `repetitive.dyn.deflate` | 16280 | 8571.5 | 2851.8 | 0.33× |
| `repetitive.fixed.deflate` | 60974 | 6368.3 | 3018.7 | 0.47× |
| `repetitive.stored.deflate` | 8389258 | 14330.3 | 36571.6 | 2.55× |
| `text.dyn.deflate` | 3050677 | 263.9 | 470.6 | 1.78× |
| `text.fixed.deflate` | 3854367 | 292.3 | 456.8 | 1.56× |
| `text.stored.deflate` | 8389258 | 15554.9 | 36618.0 | 2.35× |
| `zeros.dyn.deflate` | 8144 | 7368.9 | 7460.4 | 1.01× |
| `zeros.fixed.deflate` | 52840 | 5440.4 | 8722.6 | 1.6× |
| `zeros.stored.deflate` | 8389258 | 15114.6 | 37540.0 | 2.48× |
<!-- /perf:throughput -->

Back-to-back runs on the same machine moved the slowdown by up to about 5% on
Huffman-coded inputs and up to about 15% on stored inputs, which take about
half a millisecond and are bound by memory bandwidth. Treat a smaller change
than that as noise.

## Where the time goes

<!-- perf:profile -->
`text.dyn.deflate` (4004 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 72.0 |
| `huffman::decode` | 64.3 |
| `lz77::copy_back` | 18.1 |
| `bitstream::read_bits` | 4.2 |
| `bitstream::read_bit` | 3.1 |
| `lz77::read_length` | 2.5 |
| `lz77::read_distance` | 2.5 |
| perf (outside deflate-core) | 9.0 |
| libsystem_platform.dylib | 0.5 |

`zeros.fixed.deflate` (3999 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 22.1 |
| `huffman::decode` | 18.3 |
| `lz77::copy_back` | 17.1 |
| `bitstream::read_bit` | 2.3 |
| `bitstream::read_bits` | 2.2 |
| `lz77::read_length` | 1.8 |
| `lz77::read_distance` | 1.1 |
| libsystem_platform.dylib | 51.9 |
| libsystem_kernel.dylib | 6.2 |
| perf (outside deflate-core) | 2.2 |

`repetitive.dyn.deflate` (3999 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 15.1 |
| `block::decode_huff_block` | 11.7 |
| `huffman::decode` | 4.7 |
| `bitstream::read_bits` | 4.3 |
| `lz77::read_distance` | 2.7 |
| `lz77::read_length` | 2.3 |
| `bitstream::read_bit` | 1.8 |
| libsystem_platform.dylib | 60.4 |
| libsystem_kernel.dylib | 9.7 |
| perf (outside deflate-core) | 2.4 |
| libsystem_malloc.dylib | 0.6 |

`text.stored.deflate` (3993 samples)

| Function | Inclusive % |
| --- | ---: |
| libsystem_platform.dylib | 85.4 |
| libsystem_kernel.dylib | 14.1 |
<!-- /perf:profile -->

## Findings

1. **Huffman symbol decoding is now the cost on text.** `huffman::decode`
   still reads one bit, compares against one code length, and repeats, up to
   15 times per symbol. That is the design `huffman.rs` documents ("No decode
   table is built, which keeps the code small and the correspondence with the
   model direct"), and it is most of the remaining gap on text.
2. **Match-heavy streams now spend most of their time in `memmove`.**
   `copy_back` hands long matches to `extend_from_within`, so the remaining
   cost is the copying itself and page faults from `Vec` growth, outside
   `deflate-core`'s own logic.
3. **Stored blocks do no work in deflate-core.** The time is all `memmove` and
   kernel page faults from `Vec` growth. The output is never sized ahead, so
   growing it repeatedly reallocates and copies.
4. **Building tables costs nothing measurable.** `from_lengths` and
   `read_dynamic_tables` do not appear in any profile above, even for dynamic
   streams; `profile_attrib.py` drops shares under half a percent.

## Candidates

Each one must go through spec §16: candidate, then proof or refinement check,
then the test and differential suites, then a new run of this report and of
`make size`.

| # | Candidate | Status | Effect on the model correspondence |
| --- | --- | --- | --- |
| 1 | `copy_back`: matches of 16 bytes or more copied with `extend_from_within` in chunks that only read bytes already written; shorter ones byte by byte | Done | None on semantics. Lean `copyGo` stays byte-at-a-time; `copy_back_matches_byte_at_a_time_reference` pins equivalence for every `dist` and every `len` past the RFC maximum |
| 2 | `read_bits`: one little-endian window of up to 5 bytes, shifted and masked | Done | None: same LSB-first value, same all-or-nothing EOF check (P1); `read_bits_matches_bit_by_bit_reference_everywhere` pins it |
| 3 | Table-driven Huffman decode with a peeked bit window and the canonical walk as the fallback for long codes | Next | Changes the decode algorithm. Needs an ADR and a Lean lemma that table lookup equals the canonical decode, or an explicit statement that differential testing alone covers it. Costs binary size |
| 4 | Reserve output capacity for stored blocks, bounded by the limit | Open | None, but must keep the bomb rule: never reserve past `limit` |

## What is not in this report

No comparison against zlib or zlib-ng, and no Linux or x86 numbers. Absolute
MB/s are specific to this machine. The slowdown column is what a later
optimization should move. The Lean model's speed is not measured: it is a
specification, not a decoder anyone runs.
