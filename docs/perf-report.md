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
| Stored capacity | Also candidate 4: stored blocks reserve room for the rest of the input |
| Lazy matching | Look ahead one position; widen the Huffman table to twelve bits |
| Current | Threshold lookahead, candidate rejection, portable word comparison, and batched hash insertion |

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
| `random.stored.deflate` | 8389258 | 28122.2 | 37042.5 | 1.32× |
| `repetitive.dyn.deflate` | 16280 | 8425.1 | 3118.2 | 0.37× |
| `repetitive.fixed.deflate` | 60974 | 8765.5 | 3188.0 | 0.36× |
| `repetitive.stored.deflate` | 8389258 | 67019.3 | 37729.8 | 0.56× |
| `text.dyn.deflate` | 3050677 | 376.1 | 493.8 | 1.31× |
| `text.fixed.deflate` | 3854367 | 379.3 | 490.6 | 1.29× |
| `text.stored.deflate` | 8389258 | 59599.3 | 35153.9 | 0.59× |
| `zeros.dyn.deflate` | 8144 | 8626.6 | 7933.4 | 0.92× |
| `zeros.fixed.deflate` | 52840 | 6660.9 | 9348.8 | 1.4× |
| `zeros.stored.deflate` | 8389258 | 61737.7 | 36380.0 | 0.59× |
<!-- /perf:throughput -->

Back-to-back runs on the same machine moved the slowdown by up to about 5% on
Huffman-coded inputs and up to about 15% on stored inputs, which take about
half a millisecond and are bound by memory bandwidth. Treat a smaller change
than that as noise.

## Compression

Raw data: `scripts/reports/compress.json`. `deflate_core::deflate` (a lazy
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
| `random.raw` | 1.0001 | 1.0009 | 1.0002 | 62.7 | 411.7 | 80.8 |
| `repetitive.raw` | 0.0019 | 0.0091 | 0.0019 | 1465.2 | 10986.4 | 1637.0 |
| `text.raw` | 0.3628 | 0.5698 | 0.3633 | 53.7 | 237.4 | 110.9 |
| `zeros.raw` | 0.001 | 0.0046 | 0.001 | 1677.0 | 19192.3 | 1732.0 |
<!-- /perf:compression -->

What the table says:

- **Text.** Lazy matching produces a slightly smaller stream than level 6
  on this synthetic corpus, while level 6 still compresses faster.
- **Random bytes.** Output uses stored blocks; most work is unsuccessful
  match search followed by a discarded Huffman encoding.
- **Zeros and repeating bytes.** Ratios match level 6 at the displayed
  precision. Hash-table insertion now limits speed after eliminating
  redundant lookahead and comparing long runs in word chunks.
- **Noise and load.** Compare optimizations in alternating runs of the
  old and new binaries. Absolute throughput changes with machine load.

The current matcher preserves the old token stream. `better_next` tests
only the prefix needed to beat the current match, using
`better_match_iff_threshold` and `accept_prefix` in Lean. Older candidates
that disagree at the first byte beyond the best match are skipped; longer
comparisons use portable little-endian word loads and a byte tail. Reference
tests cover token equality, overlaps, window wrap, and comparison boundaries.
Long insertion runs iterate over bounded three-byte windows; short advances
keep the scalar path to avoid setup overhead on text. A separate reference
test compares every hash head, chain link, and insertion cursor across short
inputs and window boundaries. The finder remains checked by `accept` before
any match is emitted.

Matched measurements against the pre-optimization binary are in
`scripts/reports/matcher.json`: three alternating pairs, best of five per
input, then the median throughput per binary. The comparison keeps our own
build, test, and fuzz processes idle during timing. A separate encoder check compares complete
output bytes, and both timed binaries check round trips before timing.

<!-- perf:matcher -->
| Input | Before MB/s | After MB/s | Speedup | Bytes identical |
| --- | ---: | ---: | ---: | --- |
| `random.raw` | 59.9 | 63.5 | 1.06× | yes |
| `repetitive.raw` | 617.8 | 1465.2 | 2.37× | yes |
| `text.raw` | 37.5 | 53.6 | 1.43× | yes |
| `zeros.raw` | 649.1 | 1679.6 | 2.59× | yes |
<!-- /perf:matcher -->

The Lean side proves `decode (compress find input) = input` for every finder,
every `lengthsFor` and every input (`decode_compress`); this table measures
the Rust encoder only. The length heuristic behind the dynamic blocks is
unproved and is checked per block (ADR 0007).

## Where the time goes

<!-- perf:profile -->
`text.dyn.deflate` (4021 samples)

| Function | Inclusive % |
| --- | ---: |
| `block::decode_huff_block` | 37.7 |
| `lz77::copy_back` | 25.7 |
| `huffman::decode_fast` | 12.9 |
| `bitstream::peek_bits` | 12.4 |
| `bitstream::read_bits` | 6.8 |
| `lz77::read_length` | 5.3 |
| `lz77::read_distance` | 3.5 |
| `bitstream::skip_bits` | 2.7 |
| `huffman::from_lengths` | 0.7 |
| `bitstream::{closure#0}` | 0.7 |
| `huffman::build_fast` | 0.5 |
| perf (outside deflate-core) | 34.7 |
| libsystem_platform.dylib | 0.7 |

`zeros.fixed.deflate` (3996 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 19.4 |
| `block::decode_huff_block` | 10.7 |
| `bitstream::peek_bits` | 5.7 |
| `huffman::decode_fast` | 5.6 |
| `bitstream::read_bits` | 2.7 |
| `lz77::read_length` | 2.1 |
| `lz77::read_distance` | 1.4 |
| `bitstream::skip_bits` | 1.0 |
| libsystem_platform.dylib | 60.6 |
| libsystem_kernel.dylib | 5.7 |
| perf (outside deflate-core) | 3.0 |

`repetitive.dyn.deflate` (3991 samples)

| Function | Inclusive % |
| --- | ---: |
| `lz77::copy_back` | 17.0 |
| `block::decode_huff_block` | 13.4 |
| `bitstream::peek_bits` | 7.3 |
| `huffman::decode_fast` | 6.4 |
| `bitstream::read_bits` | 3.8 |
| `lz77::read_length` | 2.5 |
| `lz77::read_distance` | 2.1 |
| `bitstream::skip_bits` | 0.5 |
| libsystem_platform.dylib | 61.0 |
| libsystem_kernel.dylib | 5.5 |
| perf (outside deflate-core) | 2.5 |

`text.stored.deflate` (3973 samples)

| Function | Inclusive % |
| --- | ---: |
| libsystem_platform.dylib | 99.1 |

`text.raw` (3896 samples)

| Function | Inclusive % |
| --- | ---: |
| `matcher::next` | 78.7 |
| `matcher::find_best` | 41.2 |
| `matcher::better_next` | 24.4 |
| `encode_dynamic::emit_dynamic_block` | 10.6 |
| `matcher::common` | 9.5 |
| `bitwriter::write_code` | 6.1 |
| `matcher::accept` | 5.4 |
| `matcher::{closure#0}` | 5.2 |
| `matcher::insert_up_to` | 4.6 |
| `bitwriter::write_bits` | 3.8 |
| `matcher::insert` | 3.3 |
| `encode_dynamic::emit_block` | 1.5 |
| `encode_dynamic::from_tokens` | 1.4 |
| `matcher::hash_at` | 1.3 |
| `encode_dynamic::emit_blocks_iter` | 1.1 |
| `matcher::{closure#2}` | 0.7 |
| `encode_fixed::dist_sym` | 0.7 |
| `encode_fixed::dist_slot` | 0.5 |
| libsystem_platform.dylib | 4.9 |
| perf (outside deflate-core) | 2.1 |

`random.raw` (4209 samples)

| Function | Inclusive % |
| --- | ---: |
| `matcher::next` | 68.7 |
| `matcher::find_best` | 56.7 |
| `encode_dynamic::emit_dynamic_block` | 15.7 |
| `bitwriter::write_code` | 11.5 |
| `matcher::insert_up_to` | 6.9 |
| `encode_dynamic::emit_blocks_iter` | 5.2 |
| `bitwriter::write_bits` | 4.7 |
| `matcher::common` | 3.7 |
| `encode_dynamic::emit_block` | 3.7 |
| `encode_dynamic::from_tokens` | 3.7 |
| `matcher::insert` | 3.2 |
| `huffman::from_lengths` | 1.9 |
| `huffman::build_fast` | 1.5 |
| `matcher::hash_at` | 1.0 |
| `encode_dynamic::len_at` | 0.7 |
| `huffman_build::build_lengths` | 0.5 |
| `huffman_build::canonical_codes` | 0.5 |
| perf (outside deflate-core) | 1.5 |
| libsystem_malloc.dylib | 0.7 |
| libsystem_platform.dylib | 0.6 |

`zeros.raw` (4009 samples)

| Function | Inclusive % |
| --- | ---: |
| `matcher::next` | 92.7 |
| `matcher::insert_up_to` | 56.6 |
| `matcher::find_best` | 7.5 |
| `matcher::common` | 6.1 |
| `encode_dynamic::emit_dynamic_block` | 2.3 |
| `matcher::hash` | 2.1 |
| `encode_dynamic::from_tokens` | 1.4 |
| `encode_dynamic::emit_block` | 1.4 |
| `bitwriter::write_code` | 1.1 |
| `bitwriter::write_bits` | 0.8 |
| `matcher::accept` | 0.6 |
| `matcher::{closure#2}` | 0.6 |
| `encode_fixed::dist_sym` | 0.6 |
| `encode_dynamic::emit_blocks_iter` | 0.5 |
| libsystem_platform.dylib | 2.7 |

`repetitive.raw` (3995 samples)

| Function | Inclusive % |
| --- | ---: |
| `matcher::next` | 94.2 |
| `matcher::insert_up_to` | 55.9 |
| `matcher::find_best` | 10.4 |
| `matcher::common` | 8.8 |
| `encode_dynamic::emit_dynamic_block` | 1.8 |
| `matcher::better_next` | 1.3 |
| `bitwriter::write_bits` | 0.8 |
| `bitwriter::write_code` | 0.7 |
| `matcher::accept` | 0.5 |
| libsystem_platform.dylib | 2.8 |
<!-- /perf:profile -->

## Findings

1. **Text is no longer dominated by one function.** With the twelve-bit table,
   `huffman::decode_fast` and the `peek_bits` it relies on are a minority of
   text decode time, spread alongside `copy_back` and extra-bit reads. Codes
   longer than twelve bits barely reach the canonical walk. About a third of
   samples land on inlined code that `atos` does not attribute to a core
   source line, so the split among core functions is approximate.
2. **Match-heavy streams now spend most of their time in `memmove`.**
   `copy_back` hands long matches to `extend_from_within`, so the remaining
   cost is the copying itself and page faults from `Vec` growth, outside
   `deflate-core`'s own logic.
3. **Stored blocks are now bound by copying the bytes.** The first stored
   block reserves room for the rest of the input, capped by the limit, so the
   output no longer grows by doubling and copying.
4. **Building tables is a small cost on these large inputs.** `from_lengths` and
   `read_dynamic_tables` occupy little decoder time;
   `profile_attrib.py` drops shares under half a percent. Tiny blocks may
   make table construction more significant.

The same sampling command now profiles encoding the raw payloads as well.
Encoder shares use the same inclusive accounting and should not be summed.

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
| 5 | Lazy threshold search, candidate pruning, word comparisons, and batched insertion | Done | Lean proves the threshold predicate; reference tests preserve Rust tokens and hash tables, and the arbitrary-finder round-trip theorem still applies |

## What is not in this report

No comparison against zlib or zlib-ng, and no Linux or x86 numbers. Absolute
MB/s are specific to this machine. The slowdown column is what a later
optimization should move. The Lean model's speed is not measured: it is a
specification, not a decoder anyone runs.
