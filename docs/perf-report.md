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
| commit `99bbd9d` | Candidates 1 (`copy_back` in chunks) and 2 (`read_bits` from one byte window) applied |
| Current | Also candidate 3: table-driven Huffman decode (ADR 0005) |

`git show <commit>:scripts/reports/perf.json` has each earlier baseline.
Candidates 1 and 2 brought match-heavy inputs to roughly miniz_oxide's speed
or better and cut the text gap by about a sixth, without touching the Lean
model. Candidate 3 cut the remaining text gap by about a third more; its Lean
side adds definitions and a proof of equivalence and leaves the model's
decoder as it was.

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
| `random.stored.deflate` | 8389258 | 14605.8 | 35938.3 | 2.46× |
| `repetitive.dyn.deflate` | 16280 | 8287.4 | 2491.3 | 0.3× |
| `repetitive.fixed.deflate` | 60974 | 6642.7 | 2532.3 | 0.38× |
| `repetitive.stored.deflate` | 8389258 | 13202.6 | 33266.1 | 2.52× |
| `text.dyn.deflate` | 3050677 | 289.5 | 335.0 | 1.16× |
| `text.fixed.deflate` | 3854367 | 277.4 | 329.1 | 1.19× |
| `text.stored.deflate` | 8389258 | 13031.7 | 30873.6 | 2.37× |
| `zeros.dyn.deflate` | 8144 | 5598.0 | 5460.0 | 0.98× |
| `zeros.fixed.deflate` | 52840 | 4705.0 | 6573.9 | 1.4× |
| `zeros.stored.deflate` | 8389258 | 10883.1 | 29729.3 | 2.73× |
<!-- /perf:throughput -->

Back-to-back runs on the same machine moved the slowdown by up to about 5% on
Huffman-coded inputs and up to about 15% on stored inputs, which take about
half a millisecond and are bound by memory bandwidth. Treat a smaller change
than that as noise.

## Where the time goes

<!-- perf:profile -->
`text.dyn.deflate` (3999 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 40.9 |
| `lz77::copy_back` | 27.2 |
| `bitstream::peek_bits` | 15.5 |
| `huffman::decode_fast` | 13.6 |
| `bitstream::read_bits` | 8.7 |
| `lz77::read_distance` | 6.1 |
| `lz77::read_length` | 4.7 |
| `bitstream::skip_bits` | 2.1 |
| `lz77::{closure#0}` | 0.8 |
| `bitstream::{closure#0}` | 0.7 |
| `huffman::decode` | 0.5 |
| perf (outside deflate-core) | 30.8 |
| libsystem_platform.dylib | 0.6 |

`zeros.fixed.deflate` (3841 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 19.4 |
| `block::decode_huff_block` | 11.7 |
| `bitstream::peek_bits` | 6.3 |
| `huffman::decode_fast` | 6.2 |
| `bitstream::read_bits` | 3.3 |
| `lz77::read_length` | 2.2 |
| `lz77::read_distance` | 2.0 |
| `bitstream::skip_bits` | 0.9 |
| libsystem_platform.dylib | 58.7 |
| libsystem_kernel.dylib | 6.5 |
| perf (outside deflate-core) | 3.2 |
| libsystem_malloc.dylib | 0.5 |

`repetitive.dyn.deflate` (3993 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 17.0 |
| `block::decode_huff_block` | 12.4 |
| `bitstream::peek_bits` | 6.9 |
| `huffman::decode_fast` | 5.6 |
| `bitstream::read_bits` | 3.9 |
| `lz77::read_length` | 2.6 |
| `lz77::read_distance` | 2.1 |
| `bitstream::skip_bits` | 0.6 |
| libsystem_platform.dylib | 61.3 |
| libsystem_kernel.dylib | 6.8 |
| perf (outside deflate-core) | 2.3 |

`text.stored.deflate` (4001 samples)

| Function | Inclusive % |
| --- | ---: |
| libsystem_platform.dylib | 87.8 |
| libsystem_kernel.dylib | 11.7 |
<!-- /perf:profile -->

## Findings

1. **Text is no longer dominated by one function.** With the 9-bit table,
   `huffman::decode_fast` and the `peek_bits` it relies on are a minority of
   text decode time, spread alongside `copy_back` and extra-bit reads. Codes
   longer than 9 bits barely reach the canonical walk. About a third of
   samples land on inlined code that `atos` does not attribute to a core
   source line, so the split among core functions is approximate.
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
| 3 | Table-driven Huffman decode with a peeked bit window and the canonical walk as the fallback for long codes | Done | Changes the decode algorithm. ADR on table-driven Huffman decoding; Lean `decodeSymFast_eq` proves table lookup equals the canonical decode on every reader. Costs binary size |
| 4 | Reserve output capacity for stored blocks, bounded by the limit | Open | None, but must keep the bomb rule: never reserve past `limit` |

## What is not in this report

No comparison against zlib or zlib-ng, and no Linux or x86 numbers. Absolute
MB/s are specific to this machine. The slowdown column is what a later
optimization should move. The Lean model's speed is not measured: it is a
specification, not a decoder anyone runs.
