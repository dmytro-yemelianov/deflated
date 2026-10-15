# V16 holdout evaluation — preregistration

Written 2026-10-15, before any timing of the holdout bodies. Its SHA-256 is
recorded in the [v16 holdout report](library-decode-v16-holdout-report.md);
any later change to this file is a deviation and must be reported there.

## Question

Does the frozen decoder at `2222a1d` match or beat **both** pinned zlib-ng
2.3.3 and libdeflate 1.26 on any declared workload band, on inputs never used
for library tuning? This is roadmap milestone 3's first independent evaluation.
It is not a release decision: one source family per band is small, the hosts
are shared, and the `test` partition stays unused (see below).

## Frozen candidate

Built with `cargo build --locked --release` (Rust 1.88.0) from a clean
`git worktree` of `2222a1d`. No source changes are allowed in this study. If a
correctness failure appears, the study stops and reports it unfixed.

| arm64 binary (Apple M5, macOS 27.2) | SHA-256 |
|---|---|
| `library_decode` (core, fresh) | `18dde653e23497f8d2336f29acfede1d5056809713f282b527dad181c53c0672` |
| `library_decode_reuse` (core, reuse) | `88b264b81e65013bb0b460fd6e292dcda088a629ca2d7be40c1f36a8b69990af` |
| `library_decode_accel` (accel, fresh) | `29d21d9cac9f85fa76c3ad8f163255f147c4a4bb9ee6520156c4f1ceafa1e210` |
| `library_decode_reuse_accel` (accel, reuse) | `4c92c88227c60e588767426c4f5376cb93bee84001db8f91de555408e8c0082c` |

x86-64 binaries are built from the same worktree revision inside the v13
container on raps-ci; their hashes are recorded in the receipt, not here.

Native workers (arm64): `target/library-v15/workers`, built by
`library_bench.py build` from the committed `library_decode_worker.c`
(`aae153cb…`): zlib-ng decode `d940daaa…`, encode `5dabf929…`; libdeflate
decode `95de559e…`, encode `e44bf9e0…`. x86-64 workers are rebuilt from the
locked reference sources, as in v13.

## Corpus and independence

Source: the **validation** partition of `scripts/new_methods_sources.json`,
identity extraction, every body verified against its pinned Git blob SHA-1 by
`scripts/library_holdout_corpus.py` (`7ee379b0…`). `fzf-archive` is excluded
because it has no blob pin and is already compressed. Manifest SHA-256:
`12f3052615eca0ed1c8d98f49d3ad2a4b279280cd21bcea5aef92ddf6de4c7dc`.

Independence evidence: library work v1–v15 used only the six training
sources in `scripts/library_real_corpus.py`, synthetic generators and short
witnesses; no validation or test source id appears in any library report or
library script. The new-methods closure records validation bodies as
"acquisition/hash/dedup only". The **test** partition is not touched here and
stays reserved for a final release evaluation. Bodies are not redistributed.

| Case | Band | Bytes | SHA-256 (prefix) | License / origin |
|---|---|---:|---|---|
| mlflow | small | 4806 | `e7ed81c13c2baf80` | Apache-2.0 |
| typst | small | 10061 | `0b0e81e4ec058984` | Apache-2.0 |
| tensorrt | small | 15557 | `76a95556d70b9ff1` | Apache-2.0 and bundled terms |
| gltf | small | 18698 | `c9c16c8b85749f62` | CC0-1.0 |
| json-schema | small | 50423 | `cdf9b1c6253470b0` | MIT |
| penguins | small | 53098 | `144f623143c9360f` | CC0-1.0 |
| spark | medium | 83507 | `cfafe1f59cfce62c` | Apache-2.0 |
| zig | medium | 101265 | `19734568464decfe` | MIT |
| json-ld | medium | 157402 | `2b8b602eef56b0c3` | W3C test-suite terms |
| fira | medium | 403924 | `a389cef71891df12` | OFL-1.1 (TrueType font) |
| duckdb | large | 4349375 | `540dbe5d97fb50e9` | MIT; generated fixture |
| concat-all | large | 5248116 | `3acadb15e3cc901d` | derived: all 11 bodies concatenated |
| *-prefix600 (11) | tiny | 600 each | in manifest | derived: first 600 bytes of each body |

Bands: tiny < 1 KiB, small < 64 KiB, medium < 1 MiB, large ≥ 1 MiB. The large
band has only two cases from overlapping material; its interval is weak and
will be reported as such.

## Packets and implementations

Encoders: Python zlib (1.2.12), pinned zlib-ng and pinned libdeflate, each at
levels 1, 6 and 9; framings raw DEFLATE and gzip. That is 18 packets per case,
414 in all. Our own encoder is **not** included: `library_bench.py` has no
slot for it, and adding one would change the frozen controller. Every packet
is cross-decoded by Python zlib, and every decoder must reproduce it exactly
before timing.

Implementations: core (`deflate-core`), accel (`deflate-accel`; on x86-64 this
takes the runtime-detected BMI2 path), zlib-ng, libdeflate. Core runs in the
candidate slot and accel in the baseline slot of the same session, so all four
are interleaved with rotated order.

## Measurements

Controller: `scripts/library_bench.py` (`0d7e4ea8…`), unchanged.

1. **Reuse:** `measure --reuse --batched --levels 1 6 9 --sessions 5
   --minimum-ns 50000000`, reused state and output for every implementation.
2. **Fresh:** the same without `--reuse` (fresh state and output per call).
3. **First call:** `first_decode_ns` from each timed sample (first decode in a
   fresh process after one untimed validation run), descriptive only.
4. **Malformed agreement and peak RSS:** `scripts/library_holdout_checks.py`
   (`89c084da…`) on the level-6 zlib packets. Mutations: 8 truncations plus
   drop-last-byte, 16 seeded single-bit flips (seed 0x16), a one-byte suffix,
   and for gzip CRC and ISIZE flips. Python zlib is the reference; every
   decoder must reject (exit 2, no crash) when zlib rejects and produce
   zlib's exact bytes when zlib accepts. Peak RSS is whole-process `ru_maxrss`
   of one cold decode, descriptive only.
5. **Linked size:** sizes of the four Rust example binaries and of the
   reference shared libraries, descriptive only.
6. Host state: `uptime` before and after each run.

The harness also enforces truncation, wrong expected size, suffix and gzip
CRC rejection for every packet and decoder.

## Decision rule

Analysis: `scripts/library_holdout_analyze.py` (`d76a85ba…`). Per packet, the
ratio against a reference is `median_ns(reference) / median_ns(ours)` over
the five sessions (> 1 means ours is faster). For each architecture × context
(reuse, fresh) × band × framing × implementation (core, accel), the statistic
is the median packet ratio, with a 95% cluster bootstrap over source bodies
(10,000 resamples, seed 16).

A **useful-workload claim** for that cell requires, against **both**
references: median ratio ≥ 1.0, bootstrap lower bound ≥ 1.0, and no case whose
geometric-mean ratio is below 0.90. Every cell is reported, pass or fail.
Throughput MB/s is reported for orientation only; it does not decide anything.

Failure modes that stop the study: any decoder producing wrong bytes on a
valid packet, any accepted truncation/suffix/corruption, any crash, or any
malformed-input disagreement attributable to core or accel.

## Known limitations, declared now

- Both hosts are shared and loaded (M5 load average about 9 at writing; the
  x86 host runs CI runners, a VM and a background process). Paired,
  rotated, interleaved sessions mitigate but do not remove this.
- 11 source bodies, mostly JSON/text; one font; no images, logs at scale or
  binaries beyond the font. Tiny cases are prefixes, not native tiny messages.
- The same person who tuned v1–v15 chose this protocol, after seeing those
  results but before seeing any holdout timing.
