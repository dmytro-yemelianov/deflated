# Performance baseline: decode and compress

Raw data: `scripts/reports/perf.json` (decode throughput),
`scripts/reports/compress.json` (encoder ratio and speed) and
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
| commit `496e31a` | Also candidate 3: table-driven Huffman decode (ADR 0005) |
| Current | Also candidate 4: stored blocks reserve room for the rest of the input |

`git show <commit>:scripts/reports/perf.json` has each earlier baseline.
Candidates 1 and 2 brought match-heavy inputs to roughly miniz_oxide's speed
or better and cut the text gap by about a sixth, without touching the Lean
model. Candidate 3 cut the remaining text gap by roughly a quarter more; its Lean
side adds definitions and a proof of equivalence and leaves the model's
decoder as it was. The text figure recorded at `496e31a` was a fast run:
interleaved runs of that commit later measured about the same slowdown on both text inputs as the current table,
which is the number to trust. Candidate 4 took stored inputs from about
two and a half times slower than miniz_oxide to about twice as fast, and left the other
inputs where they were (interleaved runs against `496e31a`).

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
| `random.stored.deflate` | 8389258 | 70764.9 | 31885.8 | 0.45× |
| `repetitive.dyn.deflate` | 16280 | 4395.8 | 1980.6 | 0.45× |
| `repetitive.fixed.deflate` | 60974 | 4850.9 | 1984.7 | 0.41× |
| `repetitive.stored.deflate` | 8389258 | 49514.6 | 32864.3 | 0.66× |
| `text.dyn.deflate` | 3050677 | 230.7 | 306.1 | 1.33× |
| `text.fixed.deflate` | 3854367 | 234.1 | 275.7 | 1.18× |
| `text.stored.deflate` | 8389258 | 62582.4 | 34580.2 | 0.55× |
| `zeros.dyn.deflate` | 8144 | 3630.3 | 4905.6 | 1.35× |
| `zeros.fixed.deflate` | 52840 | 4330.7 | 5244.4 | 1.21× |
| `zeros.stored.deflate` | 8389258 | 59829.3 | 28719.9 | 0.48× |
<!-- /perf:throughput -->

Back-to-back runs on the same machine moved the slowdown by up to about 5% on
Huffman-coded inputs and up to about 15% on stored inputs, which take about
half a millisecond and are bound by memory bandwidth. Treat a smaller change
than that as noise.

## Compression

Raw data: `scripts/reports/compress.json`. `deflate_core::deflate` (a greedy
hash-chain matcher, then blocks of a fixed token count (ADR 0007), each dynamic-Huffman,
fixed-Huffman or the whole stream stored, whichever is smallest; M7b) against `miniz_oxide` levels 1 and 6, on the `.raw`
payloads from the same corpus. Ratio is compressed size over input size, so
lower is better; above 1 means the stream is larger than the input (stored
framing). MB/s are of input, best of 5 runs. Each stream, ours and
miniz_oxide's, is decoded with `deflate-core` and compared to the input
before it is timed.

<!-- perf:compression -->
| Input | Ratio ours | Ratio level 1 | Ratio level 6 | MB/s ours | MB/s level 1 | MB/s level 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `random.raw` | 1.0001 | 1.0009 | 1.0002 | 36.1 | 197.1 | 44.0 |
| `repetitive.raw` | 0.0019 | 0.0091 | 0.0019 | 490.4 | 6478.5 | 947.3 |
| `text.raw` | 0.3705 | 0.5698 | 0.3633 | 38.4 | 147.6 | 69.4 |
| `zeros.raw` | 0.001 | 0.0046 | 0.001 | 499.7 | 12224.6 | 945.6 |
<!-- /perf:compression -->

What the table says, and no more:

- **Text.** Our ratio is far better than level 1 and about 2% worse than
  level 6 (0.3705 against 0.3633), which is within what lazy matching would
  recover and is the next candidate. M7a's fixed-only encoder, whose figures
  are in git history at commit 63c9901, was between the two levels; the
  dynamic block is what moved it. We are slower than both levels; the
  encoder has no lazy matching and no early exit.
- **Random bytes.** The output is stored blocks, so the ratio is the stored
  framing overhead and is slightly better than miniz_oxide's. The time
  is the matcher failing to find anything.
- **Zeros and the 9-byte pattern.** Dynamic codes let a run of 258-byte
  matches cost a fraction of a bit each, and both ratios now equal level 6 to
  the four digits shown (0.0019 and 0.001), where fixed codes could not
  reach them. The matcher is far slower than miniz_oxide's run-length fast
  paths, so speed on these is the worst gap.
- **Speed against M7a, and what the first M7b recording got wrong.** The
  first M7b recording put text well under half of M7a's speed and blamed
  machine load. That was wrong. Measured back to back against M7a
  (alternating runs of both binaries on the same corpus), the slowdown was
  real, about 40% on text. The cause was per-token work repeated per block:
  `emit_blocks` walked each block's tokens five times (frequency counting
  in `lengths_for`, the used-symbol set, `fixed_bits`, `dynamic_bits`, then
  the emit), and every walk mapped each match to its length and distance
  symbols by a linear scan of the 29- and 30-entry base tables. Building
  the Huffman codes, which is per block and linear in the alphabet, was
  not the cost. The fix counts frequencies once per block, derives the used
  set and both bit sizes from the counts (the sum of frequency times code
  length, plus extra bits per symbol), and maps lengths and distances to
  symbols through precomputed tables in constant time. Each block's tokens
  are now walked once to analyse and once to emit, and the output bytes are
  unchanged (`emit_blocks_equiv_tests.rs` compares them with the old code).
  Measured back to back again, the encoder now matches M7a's speed on text
  while keeping the dynamic blocks' ratio.
- **Noise and load.** Absolute MB/s here move by tens of percent with
  machine load, and this table was recorded under load, so compare MB/s
  only between runs made back to back, and otherwise compare the ratios.
  The verified claim is that the encoder round-trips, not that it is fast.

The Lean side proves `decode (compress find input) = input` for every finder,
every `lengthsFor` and every input (`decode_compress`); this table measures
the Rust encoder only. The length heuristic behind the dynamic blocks is
unproved and is checked per block (ADR 0007).

## Where the time goes

<!-- perf:profile -->
`text.dyn.deflate` (3365 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 43.2 |
| `lz77::copy_back` | 30.0 |
| `bitstream::peek_bits` | 19.0 |
| `huffman::decode_fast` | 15.5 |
| `bitstream::read_bits` | 10.1 |
| `lz77::read_distance` | 8.4 |
| `lz77::read_length` | 4.7 |
| `bitstream::skip_bits` | 1.9 |
| `lz77::{closure#0}` | 1.8 |
| perf (outside deflate-core) | 25.3 |
| libsystem_platform.dylib | 0.8 |

`zeros.fixed.deflate` (3964 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 19.4 |
| `block::decode_huff_block` | 11.4 |
| `bitstream::peek_bits` | 6.1 |
| `huffman::decode_fast` | 5.8 |
| `bitstream::read_bits` | 3.4 |
| `lz77::read_length` | 2.4 |
| `lz77::read_distance` | 2.0 |
| `bitstream::skip_bits` | 0.8 |
| libsystem_platform.dylib | 59.2 |
| libsystem_kernel.dylib | 5.6 |
| perf (outside deflate-core) | 4.0 |

`repetitive.dyn.deflate` (3997 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 15.8 |
| `block::decode_huff_block` | 13.7 |
| `bitstream::peek_bits` | 7.2 |
| `huffman::decode_fast` | 6.7 |
| `bitstream::read_bits` | 3.7 |
| `lz77::read_length` | 2.7 |
| `lz77::read_distance` | 2.3 |
| `bitstream::skip_bits` | 0.9 |
| libsystem_platform.dylib | 59.1 |
| libsystem_kernel.dylib | 8.6 |
| perf (outside deflate-core) | 2.4 |

`text.stored.deflate` (4000 samples)

| Function | Inclusive % |
| --- | ---: |
| libsystem_platform.dylib | 99.3 |
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
3. **Stored blocks are now bound by copying the bytes.** The first stored
   block reserves room for the rest of the input, capped by the limit, so the
   output no longer grows by doubling and copying.
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
| 4 | Reserve output capacity for stored blocks, bounded by the limit | Done | None, but must keep the bomb rule: never reserve past `limit` |

## What is not in this report

No comparison against zlib or zlib-ng, and no Linux or x86 numbers. Absolute
MB/s are specific to this machine. The slowdown column is what a later
optimization should move. The Lean model's speed is not measured: it is a
specification, not a decoder anyone runs.
