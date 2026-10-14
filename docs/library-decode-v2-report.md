# Bulk decoder improvement — 2026-10-14

The second library iteration decodes a whole Huffman/LZ77 token from a single
bounded lookahead. Compared with the previous reusable-buffer implementation,
raw throughput improves 47% on the two repository inputs and 45% on the expanded
synthetic inputs. Gzip improves 37% and 38%, respectively. The bulk decoder still
trails both native references; this is progress toward the release contract,
not a competitive-release claim.

## Change and correctness boundary

The [baseline profile](../scripts/reports/library-decode-v2-profile.txt) attributes
about 40% of sampled top-of-stack frames to `copy_back` and 45% to the Huffman
block loop on `Properties.lean` compressed by libdeflate. Table construction
accounts for about 7%. Sampling is approximate, particularly with inlining.

The new path safely loads eight available input bytes without advancing the
reader. Even at an unaligned position, at least 57 real bits remain; two
12-bit symbol codes plus maximum length/distance extras need at most 42 bits.
Literal and distance lookups reuse the existing checked Huffman tables. The
reader advances only after a complete token is resolved. Table misses, reserved
symbols and short input use the old decoding path from the original position.
Output limits retain their precedence over invalid backreferences. Lookahead
can read a container suffix within the input slice but never consumes it.

The short-copy loop also computes its starting index once and is eligible for
inlining. Attempts to use general bulk-copy or pre-zeroed output for all short
matches were slower and were removed. All four screening runs, including the
negative results, remain in the [screening receipt](../scripts/reports/library-decode-v2-screening.json.gz).

This is portable safe Rust with no new dependencies or public API changes.
No new Lean refinement proof is claimed. New tests compare optimized blocks
against canonical bit-at-a-time Huffman decoding and byte-at-a-time copying:
results, exact errors, bit positions and partial output must agree. Coverage
includes arbitrary complete trees, degenerate distance trees, reserved symbols,
truncation, all bit offsets, length/distance ranges, limits and container suffixes.

## Same diagnostic corpus, fresh paired measurements

Five serial rotated sessions, 42 packets, four decoders, 840 timing rows and
588 rejection checks. Baseline is the exact previous candidate, verified by
its binary hash against the v1 receipt. Both versions use the same public-API
benchmark driver and charge known-size output allocation inside each call.
Native references use their actual gzip APIs, including checksums.

| Scope / format | Previous MB/s | Current MB/s | Speedup | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Repository / raw | 583.7 | 858.7 | 1.47× | 1554.9 | 2432.8 |
| Repository / gzip | 466.3 | 636.8 | 1.37× | 1357.1 | 2384.3 |
| Synthetic / raw | 13950.2 | 17232.9 | 1.24× | 23377.1 | 21242.3 |
| Synthetic / gzip | 2124.9 | 2185.8 | 1.03× | 7590.6 | 17137.2 |

MB/s use total raw bytes divided by summed per-packet median times. These are
new paired observations, not ratios across historical runs. Raw repository
throughput is now about 1.8× behind zlib-ng and 2.8× behind libdeflate on this
host. A few original tiny packets regress: the worst median speed ratio is
0.903× (about 11% more time). Tiny effects are only a few nanoseconds and no
universal no-regression claim is made. The raw rows retain every packet.

[Full receipt](../scripts/reports/library-decode-v2.json.gz).

## Expanded synthetic check after candidate freeze

The candidate was frozen before this evaluation and was not retuned afterward.
Eight deterministic cases cover JSON records, numeric CSV, multilingual UTF-8,
32 KiB window boundaries, literal-biased bytes, alternating random/repeated
blocks, and 31/257-byte inputs. Each is encoded by zlib, zlib-ng and libdeflate
at levels 1 and 9, in raw and gzip format. Three sessions produce 1,152 timing
rows over 96 packets, with 1,344 rejection checks. The generator and manifest
are hashed in the evidence. These are synthetic diagnostics, not independent
real application source groups or a held-out release benchmark.

| Scope / format | Previous MB/s | Current MB/s | Speedup | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Synthetic bulk / raw | 398.0 | 578.2 | 1.45× | 993.9 | 1415.0 |
| Synthetic bulk / gzip | 337.7 | 464.9 | 1.38× | 907.4 | 1377.6 |
| Tiny / raw | 992.5 | 1335.2 | 1.35× | 724.2 | 93.2 |
| Tiny / gzip | 594.8 | 754.7 | 1.27× | 670.0 | 92.5 |

The worst expanded per-packet median speed ratio is 0.988×, for a tiny random
gzip packet; all other ratios are retained in the raw rows. Tiny throughput
is not representative of large files. Session repetitions describe this fixed
corpus and machine; no confidence bound or broader generalization is claimed.

[Expanded receipt](../scripts/reports/library-decode-v2-expanded.json.gz).

## Validation and reproduction

`make test`, all-feature workspace tests, Clippy with warnings denied, and the
local Cargo package verification pass. The differential harness checks 20,197
streams with zero findings and 1,654 framing oracle checks. Bounded fuzzing
completed 6,338,991 inflate, 1,205,706 differential and 191,204 roundtrip runs
(46 elapsed seconds each), with no crash discovered. Native worker rejection
checks additionally cover truncation, suffixes, expected size and CRC damage.
Historical source/worker/decoder receipt audits pass.

The benchmark executable is 497,968 bytes versus 498,304 for the previous
candidate on this host. This is a linked benchmark-size observation, not a
peak-memory qualification or a cross-platform library-size guarantee. The core
still needs independent real-corpus, x86-64, memory and reusable-context testing.

The [v1 core source snapshot](../scripts/reports/library-decode-v1-core-sources.json.gz)
preserves the exact pre-change Rust source and driver, because that iteration
was an uncommitted working tree. Its files are checked against the v1 receipt;
restore them in a separate checkout to rebuild that baseline, keeping its
original workspace toolchain/profile. The final candidate's source and binary
hashes are recorded in both v2 receipts.

```sh
cargo build --locked --release -p deflate-core --example library_decode
python3 scripts/library_bench.py measure --workers target/library-v1/workers \
  --baseline target/library-v2/baseline_decode \
  --baseline-receipt scripts/reports/library-decode-v1.json.gz \
  --out target/library-v2/reproduce --sessions 5 --study library-decode-v2-diagnostic
python3 scripts/library_validation_corpus.py --out target/library-v2/reproduce-corpus
python3 scripts/library_bench.py measure --workers target/library-v1/workers \
  --baseline target/library-v2/baseline_decode \
  --baseline-receipt scripts/reports/library-decode-v1.json.gz \
  --corpus-manifest target/library-v2/reproduce-corpus/manifest.json --levels 1 9 \
  --out target/library-v2/reproduce-expanded --sessions 3 --study library-decode-v2-expanded
```

Use fresh output directories. Rebuilt baseline binary hashes may differ across
build paths/toolchains: omit the exact-binary receipt option when doing a new
reconstruction, and report that new build as such rather than rewriting the
original receipt. Reference build instructions remain in the [library plan](library-roadmap.md).
