# Encoder tuning: speed and size

The original benchmark has four synthetic payloads. This tuning pass adds
all [Canterbury and large Canterbury](https://corpus.canterbury.ac.nz/descriptions/)
and [Silesia](https://sun.aei.polsl.pl/~sdeor/index.php?page=silesia) files, with a fixed training
and holdout split. Data is downloaded from the corpus authors and stays in
ignored `target/`; the committed report records each file's SHA-256 and
source URL. Silesia downloads also check the author's published MD5 values.

## Why the previous matcher fell behind

The previous matcher used three-byte hashes and up to 128 probes for every
search. Common three-byte prefixes cause long chains, particularly on DNA
and text. It also indexed every byte inside a match and offered only one
search/parse policy. miniz changes its search effort with the match length,
uses a separate fast greedy path, and has compact hash links
([reference source](https://github.com/Frommi/miniz_oxide/blob/44e43c7786e379b2b1a7fde4aa0e63be719e583d/miniz_oxide/src/deflate/core.rs)). Its level 1
speed comes with much larger output than its level 6 on many inputs.

This pass uses four-byte chains for longer matches and a separate trigram
chain for short matches. Backward distances use sixteen-bit links, with
32768 retained as a legal full-window distance. Word comparisons and a
checked threshold test handle lazy matching. Uniform-byte and checked periodic insertion fill
the exact chain links in batches, including hash collisions between phases.
Balanced uses a compact trigram-only index with 128 probes for sampled short
periods, and retains the previous trigram matcher for flat byte samples where
the new path regressed. Both still search and encode, including compressible
data with flat frequencies. Tables occupy about 192–384 KiB depending on
this choice; previously they occupied about 256 KiB.

Three raw-DEFLATE presets expose the tradeoff:

- `Fast`: four probes, greedy parsing, and limited insertion inside long
  matches. It prioritizes speed while retaining stronger compression than
  a single-probe parser on many inputs.
- `Balanced`: sixty-four probes and lazy parsing, or the 128-probe trigram
  paths described above; the default for `deflate`.
- `Best`: 512 probes and lazy parsing, plus block splitting when estimated
  encoded header and payload costs favor a quarter-boundary split. This
  spends extra CPU on smaller output.

```rust
use deflate_core::{CompressionLevel, deflate_with_level};
let packed = deflate_with_level(b"example payload", CompressionLevel::Fast);
```

The presets change the heuristic, so compressed bytes may change. Presets
are not ordered by speed on every input: the adaptive Balanced paths are
faster than Fast on the synthetic stress set. Choose using the workload
measurements rather than assuming a universal winner. Every
emitted match still passes `accept` and every Huffman length set passes
`valid_lengths`. The existing Lean theorems quantify over every finder and
checked split policy; they establish model correctness, not optimal size
or speed. Rust correspondence is tested, with no refinement proof.

## Measurements

Raw data: [`scripts/reports/tuning.json`](../scripts/reports/tuning.json).
Apple M5, Rust 1.88, normal release build, miniz_oxide 0.8.9. Timings are
medians of five batches lasting at least twenty milliseconds, rotating
algorithm order. Every produced stream is checked with both decoders before
timing. Aggregate throughput divides total input bytes by the sum of
per-file median encode times; output size sums separately compressed files.
Tables compare Fast with level 1, Balanced with level 6, and Best with
level 9. Lower size percentages and higher speed multiples are better.
“Wins both” counts files with strictly faster encoding and no larger output.
The previous default is commit `04eae11`, built with the same timing harness
and build flags. Other work was active on this machine, so small timing
differences should be treated as noise. Size measurements are deterministic.

Training data selected the preset search budgets before the held-out files
were measured. The original synthetic corpus also serves as a regression
check: it exposed random and periodic-input regressions in the first dual
index candidate, leading to the compact-index choice and periodic batching.
The final measurements below recheck both partitions after those corrections.

<!-- tuning:train -->
| Preset | MB/s | Speed vs previous | Size vs previous | Speed vs reference | Size vs reference | Wins both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast (vs level 1) | 149.6 | 5.78× | +8.90% | 0.43× | -21.46% | 0/13 |
| balanced (vs level 6) | 50.7 | 1.96× | -0.28% | 0.90× | -0.53% | 4/13 |
| best (vs level 9) | 26.4 | 1.02× | -1.27% | 1.12× | -0.51% | 4/13 |
<!-- /tuning:train -->

Held-out files include Shakespeare, technical text, poetry, spreadsheets,
the world factbook, executable archives, source archives, databases, a
dictionary, a PDF, and an image.

<!-- tuning:holdout -->
| Preset | MB/s | Speed vs previous | Size vs previous | Speed vs reference | Size vs reference | Wins both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast (vs level 1) | 92.6 | 2.56× | +5.76% | 0.32× | -17.06% | 0/13 |
| balanced (vs level 6) | 51.7 | 1.43× | +0.03% | 0.93× | -0.54% | 1/13 |
| best (vs level 9) | 29.8 | 0.82× | -0.59% | 0.97× | -0.82% | 2/13 |
<!-- /tuning:holdout -->

The original seeded synthetic corpus checks random data, long periodic
runs, text, and zeros. It also remains the corpus used for profiling.

<!-- tuning:stress -->
| Preset | MB/s | Speed vs previous | Size vs previous | Speed vs reference | Size vs reference | Wins both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast (vs level 1) | 95.7 | 0.86× | +0.81% | 0.17× | -13.10% | 0/4 |
| balanced (vs level 6) | 133.7 | 1.20× | +0.00% | 0.77× | -0.05% | 2/4 |
| best (vs level 9) | 71.7 | 0.64× | -0.00% | 0.41× | -0.05% | 1/4 |
<!-- /tuning:stress -->

These comparisons establish a tradeoff on this corpus and machine. They do
not establish a universal winner across DEFLATE implementations or CPUs.

## Reproduce

```sh
python3 scripts/tuning_corpus.py
python3 scripts/tuning_report.py --baseline-ref 04eae11
# To refresh the committed report and its generated tables:
python3 scripts/tuning_report.py --baseline-ref 04eae11 --record
python3 scripts/tuning_report.py --check
```

The training sweep tried chain budgets sixteen, thirty-two, sixty-four,
and 128, plus the fast four-probe and deeper 512-probe settings. Sixty-four
retained the previous size tradeoff with much less chain work; the other
presets provide different points on the curve. Thin LTO with one codegen
unit regressed the trial throughput and was not adopted. Further work
should target the remaining emitter cost, per-block stored fallback for
mixed data, and parsing decisions based on encoded bit cost.
