# V16 holdout evaluation

This is the first independent evaluation of the decoder (roadmap milestone 3).
The protocol was fixed in the [preregistration](library-decode-v16-preregistration.md)
(SHA-256 `464fefecab6cada50e4a789bcdb475e8c310c8fa0ee642e25c32dba4dc69d7be`)
before any holdout timing. The candidate was frozen at `2222a1d`, and no
source changed during the study.

## Verdict

**No workload qualifies.** The preregistered rule needs a match or win against
**both** zlib-ng and libdeflate. libdeflate was faster in every one of the 64
cells: 2 architectures × 2 contexts × 4 bands × 2 framings × 2
implementations. The best result against libdeflate was arm64 tiny raw with
fresh calls (core 0.95×, CI [0.92, 1.01]), which is still below the bar.

Against zlib-ng alone, the result splits by architecture and implementation:

| Cells passing the rule vs zlib-ng only | core | accel |
|---|---|---|
| arm64, reuse (8 cells) | 4: all raw bands | 8: every band, raw and gzip |
| arm64, fresh | 3: small/medium/large raw | 6: small/medium/large, raw and gzip |
| x86-64, reuse | 0 | 4: small and large, raw and gzip |
| x86-64, fresh | 0 | 2: small raw and gzip |

On held-out data, then, `deflate-accel` reliably beats zlib-ng on arm64 and
partly on x86-64. The portable core beats zlib-ng only for raw DEFLATE on
arm64. Neither is competitive with libdeflate yet. Median ratios against
libdeflate for small to large inputs:

| | arm64 raw | arm64 gzip | x86-64 raw | x86-64 gzip |
|---|---|---|---|---|
| core | 0.77–0.88× | 0.51–0.64× | 0.63–0.69× | 0.46–0.58× |
| accel | 0.80–0.88× | 0.79–0.85× | 0.74–0.79× | 0.73–0.78× |

## Corpus and independence

Eleven bodies from the **validation** partition of
`scripts/new_methods_sources.json`, each verified against its pinned Git blob
SHA-1 by `scripts/library_holdout_corpus.py`. Twelve derived cases were added:
a 600-byte prefix of each body (tiny band) and the concatenation of all bodies
(large band). No validation or test source id appears in any v1–v15 library
report or script; library tuning used six training sources and synthetic
generators only. The **test** partition was not touched and remains reserved.
Bodies are not redistributed; the receipt keeps names, sizes, hashes and
licenses.

Every one of the 414 packets (Python zlib, zlib-ng and libdeflate encoders at
levels 1/6/9, raw and gzip) was cross-decoded by Python zlib. Before timing,
each decoder reproduced it exactly and rejected truncation, wrong size, a
suffix and (gzip) a corrupted CRC. That is 6,624 rejection checks per run.

## Where the gap is

- **Portable gzip CRC is the biggest single loss on held-out data.** Core
  gzip is far behind core raw on highly compressible JSON: spark at level 6
  runs at 0.28× libdeflate for core gzip, against 0.72× for accel. Core's
  worst gzip files (spark, json-schema) fall to 0.26–0.38× libdeflate. Accel
  removes most of this. The portable CRC (about 4 GB/s) caps any core gzip
  claim on output-heavy inputs.
- **x86-64 bulk decoding.** Even with BMI2, accel raw is 0.74–0.79×
  libdeflate on medium and large inputs and roughly level with zlib-ng.
  Core raw trails zlib-ng on x86-64 (0.88–0.99×). The v14 instruction-count
  gap remains the main explanation.
- **Tiny inputs (600 B).** On arm64 both of ours are 4–10% slower than
  libdeflate (0.91–0.96×) and level with or slightly ahead of zlib-ng. On
  x86-64 they are at 0.62–0.67× libdeflate and 0.91–1.02× zlib-ng. The worst
  tiny files are `fira-prefix600` (font bytes) and `json-schema-prefix600`.
- **Recurring worst files:** spark and json-schema (small/medium, highly
  compressible JSON), duckdb/concat-all (large NDJSON), and fira (binary font).

## Correctness on malformed input

`scripts/library_holdout_checks.py` mutated each case's zlib level-6 packet
(raw and gzip): 9 truncations, 16 seeded bit flips, a suffix, and for gzip
CRC and ISIZE flips. That is 1,242 mutations per architecture, of which
Python zlib accepted 301 (mostly flips that still decode). On both arm64 and
x86-64, **all four decoders agreed with zlib on every mutation**: they
rejected with exit status 2 when zlib rejected, and produced zlib's exact
bytes when zlib accepted. There were no crashes or disagreements. Error
kinds were not compared.

## First call, memory and size

First call (`first_decode_ns`: the first decode in a fresh process, including
decoder construction and output allocation; median over packets):

| Band / frame | arm64 core | arm64 accel | arm64 zlib-ng | arm64 libdeflate | x86 core | x86 accel | x86 zlib-ng | x86 libdeflate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tiny raw (reuse run) | 11.8 µs | 13.2 µs | 23.8 µs | 13.8 µs | 18.3 µs | 24.7 µs | 22.5 µs | 15.6 µs |
| tiny gzip (reuse run) | 12.9 µs | 13.1 µs | 23.3 µs | 23.1 µs | 22.4 µs | 25.3 µs | 23.8 µs | 17.1 µs |
| large raw (reuse run) | 4.29 ms | 4.36 ms | 5.10 ms | 3.60 ms | 8.67 ms | 7.91 ms | 7.79 ms | 6.58 ms |
| large gzip (reuse run) | 5.66 ms | 4.52 ms | 5.55 ms | 3.63 ms | 10.57 ms | 8.41 ms | 8.13 ms | 6.91 ms |

These are single first calls with cold caches and page faults. They are
descriptive only and noisy. On x86-64, accel's first tiny call is slower
than core's, which is consistent with one-time CPU feature detection.

Peak RSS (whole process, one cold decode, gzip): on arm64 core and accel use
about 50–60 KiB more than zlib-ng and 100–130 KiB more than libdeflate at every
size. For example, duckdb (4.1 MiB output) peaks at 7,360 KiB for core and
accel, 7,312 KiB for zlib-ng and 7,232 KiB for libdeflate. **The x86-64 RSS
numbers are not usable:** every decoder reads a flat ~10 MiB because Linux
`ru_maxrss` for the child includes the forked Python image before `exec`.
See deviations.

Linked size (descriptive): the Rust example workers are 553–570 KB on arm64
and 596–634 KB on x86-64, including the Rust standard library, so they are
not a decoder-only size. Accel adds about 2–17 KB on arm64 and 35–38 KB on x86-64
(the BMI2 copies of the decode loop plus `crc32fast`). The reference
shared libraries are 159 KB / 121 KB (zlib-ng / libdeflate dylib, arm64) and
209 KB / 135 KB (`.so`, x86-64), and they include their encoders. A
decoder-only linked-size comparison has not been done.

## Hosts and conditions

- **arm64:** Apple M5, macOS 27.2, Rust 1.88.0, Apple clang 21. Load average
  was 9 at preregistration and 12–14 during the reuse run (other user
  processes), then 5–9. Paired, rotated and interleaved sessions mitigate this
  but do not remove it.
- **x86-64:** raps-ci (Intel i7-8700, Linux 6.8), the `deflated-x86-perf:v13`
  image with **no added capabilities** (counters were not needed), the
  `~/deflated-x86` work directory, and everything pinned with `taskset -c 1`.
  Load average was 2.0–3.0 on 12 threads, with CI runners, a Windows VM and a
  background process present. Rust and the references were rebuilt in the
  container from `2222a1d` and the locked reference sources. Container
  binary hashes: core `d6396996…`/`142bfc5c…` (fresh/reuse), accel
  `d3d94405…`/`142ac78d…`.
- The container and work directory were removed afterwards; the image was kept.

## Deviations from the preregistration

1. **x86-64 peak RSS is invalid** (fork-before-exec artifact, above). The
   arm64 numbers use `posix_spawn` semantics and are meaningful. A Linux
   rerun would need `/usr/bin/time -v`-style accounting of the worker alone.
2. **First-call description.** The preregistration said `first_decode_ns`
   comes "after one untimed validation run". The validation run is a
   separate process, so the metric is a genuine in-process first call. The
   metric itself did not change, only its description.
3. **Load.** The arm64 load was higher during the reuse run (12–14) than the
   level declared at writing (about 9).
4. **Large band** has two overlapping cases (duckdb is part of concat-all),
   so its bootstrap intervals are narrow by construction and should not be
   read as precise. The preregistration declared this weakness.

No analysis choice changed after seeing results. The full cell tables below
come straight from `scripts/library_holdout_analyze.py` on the archived rows.

## Full results

Ratios are `reference_ns / ours_ns` (> 1 means ours is faster). Each median is
over packets, with a 95% cluster-bootstrap interval over source bodies. "Worst
file" is the case with the lowest geometric-mean ratio. "Rule" is the
preregistered both-references rule.

### arm64 (Apple M5), reused state and output

| Band | Frame | Impl | MB/s ours / zlib-ng / libdeflate | vs zlib-ng: median [95% CI], worst file | vs libdeflate: median [95% CI], worst file | Rule |
|---|---|---|---|---|---|---|
| tiny | raw | core | 271 / 262 / 296 | 1.02 [1.00, 1.07], fira-prefix600 0.94 | 0.93 [0.90, 0.99], fira-prefix600 0.69 | fail |
| tiny | raw | accel | 276 / 262 / 296 | 1.04 [1.02, 1.08], fira-prefix600 0.96 | 0.96 [0.92, 1.00], fira-prefix600 0.71 | fail |
| tiny | gzip | core | 260 / 259 / 296 | 1.02 [0.97, 1.05], fira-prefix600 0.90 | 0.91 [0.84, 0.95], fira-prefix600 0.66 | fail |
| tiny | gzip | accel | 274 / 259 / 296 | 1.07 [1.03, 1.10], fira-prefix600 0.95 | 0.95 [0.86, 1.02], fira-prefix600 0.69 | fail |
| small | raw | core | 2423 / 1859 / 2704 | 1.28 [1.21, 1.31], gltf 1.21 | 0.88 [0.86, 0.89], gltf 0.86 | fail |
| small | raw | accel | 2433 / 1859 / 2704 | 1.28 [1.22, 1.31], gltf 1.19 | 0.88 [0.85, 0.91], gltf 0.84 | fail |
| small | gzip | core | 1412 / 1615 / 2599 | 0.92 [0.79, 1.11], json-schema 0.68 | 0.58 [0.47, 0.71], json-schema 0.37 | fail |
| small | gzip | accel | 2178 / 1615 / 2599 | 1.35 [1.31, 1.37], mlflow 1.23 | 0.85 [0.84, 0.88], json-schema 0.77 | fail |
| medium | raw | core | 1070 / 813 / 1240 | 1.26 [1.15, 1.29], spark 1.07 | 0.86 [0.79, 0.87], spark 0.81 | fail |
| medium | raw | accel | 1050 / 813 / 1240 | 1.25 [1.09, 1.29], spark 1.01 | 0.84 [0.79, 0.85], spark 0.77 | fail |
| medium | gzip | core | 830 / 792 / 1371 | 0.89 [0.62, 1.03], spark 0.58 | 0.52 [0.27, 0.63], spark 0.26 | fail |
| medium | gzip | accel | 1079 / 792 / 1371 | 1.42 [1.36, 1.45], fira 1.36 | 0.79 [0.69, 0.83], spark 0.66 | fail |
| large | raw | core | 1194 / 999 / 1476 | 1.18 [1.13, 1.19], concat-all 1.18 | 0.81 [0.78, 0.84], concat-all 0.77 | fail |
| large | raw | accel | 1187 / 999 / 1476 | 1.16 [1.15, 1.17], duckdb 1.18 | 0.82 [0.81, 0.85], concat-all 0.79 | fail |
| large | gzip | core | 900 / 910 / 1412 | 1.02 [0.99, 1.03], concat-all 0.97 | 0.64 [0.63, 0.66], concat-all 0.63 | fail |
| large | gzip | accel | 1143 / 910 / 1412 | 1.27 [1.19, 1.30], concat-all 1.21 | 0.83 [0.75, 0.85], concat-all 0.79 | fail |

### arm64 (Apple M5), fresh state per call

| Band | Frame | Impl | MB/s ours / zlib-ng / libdeflate | vs zlib-ng: median [95% CI], worst file | vs libdeflate: median [95% CI], worst file | Rule |
|---|---|---|---|---|---|---|
| tiny | raw | core | 270 / 271 / 271 | 1.00 [0.98, 1.04], fira-prefix600 0.95 | 0.95 [0.92, 1.01], fira-prefix600 0.78 | fail |
| tiny | raw | accel | 266 / 271 / 271 | 0.98 [0.97, 1.01], fira-prefix600 0.94 | 0.94 [0.91, 0.99], fira-prefix600 0.78 | fail |
| tiny | gzip | core | 261 / 263 / 273 | 1.00 [0.98, 1.02], gltf-prefix600 0.93 | 0.93 [0.91, 0.97], fira-prefix600 0.75 | fail |
| tiny | gzip | accel | 264 / 263 / 273 | 1.01 [1.00, 1.04], fira-prefix600 0.94 | 0.94 [0.92, 0.98], fira-prefix600 0.75 | fail |
| small | raw | core | 2469 / 2049 / 2792 | 1.20 [1.15, 1.24], json-schema 1.13 | 0.87 [0.85, 0.91], json-schema 0.83 | fail |
| small | raw | accel | 2426 / 2049 / 2792 | 1.20 [1.15, 1.23], json-schema 1.11 | 0.88 [0.84, 0.90], json-schema 0.82 | fail |
| small | gzip | core | 1431 / 1650 / 2633 | 0.87 [0.74, 1.04], json-schema 0.68 | 0.54 [0.46, 0.72], json-schema 0.38 | fail |
| small | gzip | accel | 2197 / 1650 / 2633 | 1.33 [1.30, 1.36], typst 1.27 | 0.84 [0.80, 0.86], json-schema 0.77 | fail |
| medium | raw | core | 1250 / 938 / 1465 | 1.24 [1.04, 1.33], spark 1.05 | 0.83 [0.80, 0.86], spark 0.80 | fail |
| medium | raw | accel | 1226 / 938 / 1465 | 1.21 [1.08, 1.32], spark 1.10 | 0.82 [0.80, 0.86], json-ld 0.81 | fail |
| medium | gzip | core | 894 / 854 / 1451 | 0.83 [0.58, 1.02], spark 0.57 | 0.51 [0.30, 0.66], spark 0.28 | fail |
| medium | gzip | accel | 1178 / 854 / 1451 | 1.40 [1.34, 1.44], json-ld 1.34 | 0.81 [0.72, 0.83], spark 0.70 | fail |
| large | raw | core | 1208 / 1076 / 1573 | 1.14 [1.12, 1.15], duckdb 1.09 | 0.77 [0.76, 0.78], duckdb 0.76 | fail |
| large | raw | accel | 1232 / 1076 / 1573 | 1.16 [1.13, 1.17], duckdb 1.11 | 0.80 [0.80, 0.80], duckdb 0.77 | fail |
| large | gzip | core | 910 / 964 / 1512 | 0.95 [0.93, 0.95], duckdb 0.94 | 0.60 [0.59, 0.61], duckdb 0.59 | fail |
| large | gzip | accel | 1198 / 964 / 1512 | 1.24 [1.24, 1.24], concat-all 1.24 | 0.79 [0.78, 0.80], duckdb 0.79 | fail |

### x86-64 (i7-8700), reused state and output

| Band | Frame | Impl | MB/s ours / zlib-ng / libdeflate | vs zlib-ng: median [95% CI], worst file | vs libdeflate: median [95% CI], worst file | Rule |
|---|---|---|---|---|---|---|
| tiny | raw | core | 189 / 195 / 300 | 0.97 [0.92, 1.01], json-schema-prefix600 0.87 | 0.64 [0.62, 0.65], fira-prefix600 0.57 | fail |
| tiny | raw | accel | 194 / 195 / 300 | 0.99 [0.95, 1.04], json-schema-prefix600 0.89 | 0.65 [0.64, 0.67], fira-prefix600 0.59 | fail |
| tiny | gzip | core | 185 / 189 / 296 | 0.97 [0.92, 1.02], json-schema-prefix600 0.87 | 0.62 [0.61, 0.65], fira-prefix600 0.58 | fail |
| tiny | gzip | accel | 196 / 189 / 296 | 1.02 [0.98, 1.07], json-schema-prefix600 0.96 | 0.67 [0.65, 0.69], fira-prefix600 0.60 | fail |
| small | raw | core | 1353 / 1469 / 2145 | 0.95 [0.88, 1.05], penguins 0.86 | 0.63 [0.62, 0.65], json-schema 0.61 | fail |
| small | raw | accel | 1630 / 1469 / 2145 | 1.10 [1.07, 1.18], json-schema 1.02 | 0.75 [0.72, 0.77], json-schema 0.71 | fail |
| small | gzip | core | 937 / 1379 / 1996 | 0.66 [0.56, 0.94], json-schema 0.47 | 0.46 [0.38, 0.58], json-schema 0.33 | fail |
| small | gzip | accel | 1570 / 1379 / 1996 | 1.13 [1.07, 1.26], json-schema 1.03 | 0.77 [0.73, 0.81], json-schema 0.72 | fail |
| medium | raw | core | 628 / 664 / 959 | 0.88 [0.80, 0.96], spark 0.78 | 0.64 [0.59, 0.65], spark 0.59 | fail |
| medium | raw | accel | 725 / 664 / 959 | 1.07 [0.87, 1.10], spark 0.84 | 0.75 [0.64, 0.80], spark 0.64 | fail |
| medium | gzip | core | 519 / 653 / 928 | 0.65 [0.35, 0.85], spark 0.34 | 0.48 [0.27, 0.59], spark 0.26 | fail |
| medium | gzip | accel | 695 / 653 / 928 | 1.04 [0.88, 1.08], spark 0.86 | 0.74 [0.69, 0.80], spark 0.67 | fail |
| large | raw | core | 742 / 828 / 1072 | 0.90 [0.89, 0.90], duckdb 0.89 | 0.69 [0.69, 0.69], duckdb 0.69 | fail |
| large | raw | accel | 848 / 828 / 1072 | 1.03 [1.03, 1.04], duckdb 1.02 | 0.79 [0.79, 0.79], concat-all 0.79 | fail |
| large | gzip | core | 588 / 790 / 1012 | 0.75 [0.75, 0.75], duckdb 0.74 | 0.58 [0.58, 0.58], duckdb 0.58 | fail |
| large | gzip | accel | 797 / 790 / 1012 | 1.01 [1.00, 1.01], duckdb 1.00 | 0.78 [0.78, 0.79], duckdb 0.79 | fail |

### x86-64 (i7-8700), fresh state per call

| Band | Frame | Impl | MB/s ours / zlib-ng / libdeflate | vs zlib-ng: median [95% CI], worst file | vs libdeflate: median [95% CI], worst file | Rule |
|---|---|---|---|---|---|---|
| tiny | raw | core | 180 / 190 / 256 | 0.94 [0.88, 0.97], json-schema-prefix600 0.83 | 0.65 [0.63, 0.68], fira-prefix600 0.64 | fail |
| tiny | raw | accel | 175 / 190 / 256 | 0.91 [0.87, 0.94], json-schema-prefix600 0.83 | 0.63 [0.62, 0.65], fira-prefix600 0.62 | fail |
| tiny | gzip | core | 172 / 185 / 251 | 0.93 [0.87, 0.99], json-schema-prefix600 0.81 | 0.64 [0.61, 0.66], fira-prefix600 0.65 | fail |
| tiny | gzip | accel | 179 / 185 / 251 | 0.96 [0.92, 1.00], json-schema-prefix600 0.89 | 0.67 [0.65, 0.68], fira-prefix600 0.66 | fail |
| small | raw | core | 1421 / 1466 / 2083 | 0.96 [0.91, 1.08], gltf 0.91 | 0.66 [0.65, 0.69], json-schema 0.65 | fail |
| small | raw | accel | 1591 / 1466 / 2083 | 1.08 [1.02, 1.17], gltf 1.00 | 0.74 [0.71, 0.77], json-schema 0.71 | fail |
| small | gzip | core | 942 / 1371 / 1950 | 0.67 [0.57, 0.95], json-schema 0.48 | 0.48 [0.41, 0.59], json-schema 0.34 | fail |
| small | gzip | accel | 1552 / 1371 / 1950 | 1.10 [1.03, 1.26], gltf 1.02 | 0.77 [0.73, 0.82], gltf 0.73 | fail |
| medium | raw | core | 659 / 658 / 954 | 0.99 [0.80, 1.03], spark 0.78 | 0.67 [0.62, 0.70], spark 0.62 | fail |
| medium | raw | accel | 718 / 658 / 954 | 1.07 [0.85, 1.17], spark 0.81 | 0.74 [0.64, 0.79], spark 0.65 | fail |
| medium | gzip | core | 538 / 644 / 919 | 0.70 [0.35, 0.89], spark 0.34 | 0.51 [0.28, 0.62], spark 0.27 | fail |
| medium | gzip | accel | 684 / 644 / 919 | 1.05 [0.88, 1.12], spark 0.84 | 0.73 [0.67, 0.78], spark 0.67 | fail |
| large | raw | core | 681 / 762 / 990 | 0.89 [0.89, 0.90], duckdb 0.88 | 0.69 [0.68, 0.69], duckdb 0.69 | fail |
| large | raw | accel | 741 / 762 / 990 | 0.97 [0.97, 0.97], duckdb 0.97 | 0.75 [0.74, 0.75], concat-all 0.74 | fail |
| large | gzip | core | 538 / 722 / 938 | 0.75 [0.75, 0.75], concat-all 0.74 | 0.57 [0.57, 0.58], concat-all 0.57 | fail |
| large | gzip | accel | 690 / 722 / 938 | 0.96 [0.95, 0.96], duckdb 0.95 | 0.74 [0.73, 0.74], concat-all 0.74 | fail |

## Reproduce

```sh
python3 scripts/library_holdout_corpus.py --out target/library-v16/corpus
git worktree add --detach target/library-v16/src 2222a1d
(cd target/library-v16/src && CARGO_TARGET_DIR=../build cargo build --locked --release \
  -p deflate-core --example library_decode --example library_decode_reuse \
  -p deflate-accel --example library_decode_accel --example library_decode_reuse_accel)
B=target/library-v16/build/release/examples W=target/library-v15/workers M=target/library-v16/corpus/manifest.json
python3 scripts/library_bench.py measure --workers $W --candidate $B/library_decode_reuse \
  --baseline $B/library_decode_reuse_accel --reuse --batched --out target/library-v16/arm64-reuse \
  --corpus-manifest $M --levels 1 6 9 --sessions 5 --minimum-ns 50000000 --study v16-holdout-arm64-reuse
python3 scripts/library_bench.py measure --workers $W --candidate $B/library_decode \
  --baseline $B/library_decode_accel --batched --out target/library-v16/arm64-fresh \
  --corpus-manifest $M --levels 1 6 9 --sessions 5 --minimum-ns 50000000 --study v16-holdout-arm64-fresh
python3 scripts/library_holdout_checks.py --corpus $M --core $B/library_decode \
  --accel $B/library_decode_accel --workers $W --out target/library-v16/arm64-checks
# x86-64: inside deflated-x86-perf:v13 with no added capabilities, repository at 2222a1d:
#   library_x86_counters.py references + library_bench.py build (as in v13), then the
#   same measure/check commands under `taskset -c 1`; reports copied to target/library-v16/x86/
python3 scripts/library_holdout_analyze.py --corpus $M target/library-v16/{arm64-reuse,arm64-fresh}/report.json \
  target/library-v16/x86/{x86-reuse,x86-fresh}/report.json
python3 scripts/archive_v16_holdout.py && python3 scripts/archive_v16_holdout.py --check
```

The receipt `scripts/reports/library-decode-v16-holdout.json.gz` holds every
timing row (column-wise), packet hashes, binary/library hashes, toolchains,
host load records, the malformed-input rows' summary and disagreements (none),
peak RSS rows and the verdicts. `--check` re-runs the preregistered analysis
on the archived rows and confirms that it reproduces the stored verdicts.

## What this means for the roadmap

The release gate in the roadmap requires a useful workload where we match or
beat **both** references. Nothing here meets it. The evidence points to three
next steps:

1. Core gzip is capped by the portable CRC on output-heavy data. Either
   recommend `deflate-accel` for gzip, or find a faster safe portable CRC
   (folding with wider tables).
2. On x86-64 the remaining gap is instruction count in the bulk loop (v13/v14).
   libdeflate's multi-literal table entries and its handling of full-table
   lengths are the obvious next mechanisms.
3. Tiny-message setup on x86-64.

This holdout is now spent for tuning claims. Any later improvement must be
judged on the reserved **test** partition, or on new preregistered data.
