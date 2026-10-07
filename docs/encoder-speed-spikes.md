# P2: isolated encoder speed experiments

Status: training pilot complete; validation and auxiliary guards pending.
The current production core is unchanged. The principal 1.5×/+1% goal is
not established by these results.

All variants are built from the sealed S9 source archive with rustc 1.88.0
and identical release flags. The rebuilt no-change control has the exact
SHA-256 of the original native worker, `52906b4f7880f7882634f150230e52a44cd3814bf0ac9b3f52306b49aef1bea9`.
The three experimental implementations preserve search coverage:

- `reverse`: replace scalar code-bit reversal with `u32::reverse_bits`,
  keeping the existing 32-bit clamp and guarding width zero.
- `iterator`: retain position-plus-one chain links in an explicit sentinel
  iterator, preserving candidate order and the probe bound.
- `accept`: simplify range arithmetic after equivalent bounds checks,
  retaining the full match byte comparison, including overlaps.

Each isolated build passed 27 library tests. Additional equivalence checks
cover all 16-bit words and widths, 32-bit/clamped widths and bit offsets,
overflow/invalid match ranges, and chain traversal through three ring wraps.

Five serial paired warm sessions compare six methods on eight new real
training inputs and three previous S9 outliers: 1320 paired rows. Both native
workers check their packets with the Rust and miniz decoders; Python checks
zlib decoding and exact consumption. Every pair has identical packet lengths
and SHA-256 hashes for both the selected method and its internal Balanced
control. Direct byte comparisons were added to subsequent campaigns; the
exact driver of this first pilot is preserved separately.

| Variant | Balanced speed | Old compromise speed | Old fast-candidate speed | Best speed | Old size-policy speed |
| --- | ---: | ---: | ---: | ---: | ---: |
| No-change control | 0.981× | 1.000× | 0.998× | 1.006× | 1.006× |
| Code reversal | 1.053× | 1.055× | 1.118× | 1.022× | 1.018× |
| Chain iterator | 0.988× | 1.005× | 0.989× | 0.990× | 0.993× |
| Acceptance bounds | 0.988× | 1.015× | 0.995× | 0.983× | 0.976× |

These are real-training summed per-file median speed ratios against the
original **same method**. They are not final confidence bounds. Packed sizes
are unchanged. The no-change control demonstrates noise at the percent scale;
neither the iterator nor acceptance rewrite warrants retention. Code reversal
is the only clearly useful candidate here and advances to validation.

The all-three combination was compiled and tested but not measured or selected:
combining independently negative experiments would spend the search budget
without a supported reason. A bounded follow-up within the matcher bookkeeping
spike will test progression arithmetic after accepted-match bounds; this is
not a new search-coverage optimization.

The fresh synthetic corpus adds 60 inputs, 20 per split, using disjoint regimes
7–12 across actual-hash collisions, competing match costs, drift/change points,
random islands, sampling traps, ring wraps and six paired transformations.
Regeneration, aligned hash collisions and transformation relationships are
checked. No selector features or encoder labels have been extracted for the
new synthetic or real final-test inputs.

[Full pilot metadata](../scripts/reports/encoder-p2-initial.json),
[paired raw ledger](../scripts/reports/encoder-p2-initial-measurements.jsonl.gz),
[exact initial driver](../scripts/reports/encoder-p2-initial-driver.py.gz), and
[synthetic construction metadata](../scripts/reports/encoder-synthetic.json)
retain results, hashes and rejected alternatives.

```sh
python3 scripts/encoder_synthetic.py
python3 scripts/encoder_synthetic.py --check
python3 scripts/test_encoder_tools.py
python3 scripts/encoder_spikes.py --out target/encoder-performance/p2-builds-NEW
# Select control/reverse/iterator/accept receipts into a study manifest.
python3 scripts/encoder_compare.py --builds STUDY.json --out target/encoder-performance/p2-study-NEW
```

Reproduction needs the sealed baseline and real/regression inputs described
in [the profiling report](encoder-profile-report.md). Native timings include
allocations, matching, policies and emission, excluding I/O and validation.
This pilot has no first-call confidence, independent test results, integrated
binary-size evidence or auxiliary memory/tiny guard verdicts. P3/P4 algorithmic
experiments and the final P5/P6 campaign remain required.
