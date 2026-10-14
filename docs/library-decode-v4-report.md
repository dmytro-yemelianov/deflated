# Dynamic Huffman preparation — 2026-10-14

The fourth iteration reduces dynamic Huffman preparation overhead and fixes
integer overflow in the public table constructor. On the same six real files,
fresh-output raw throughput rises from 664.8 to 690.2 MB/s (+3.8%) relative to
the exact v3 candidate; gzip rises from 523.4 to 535.5 MB/s (+2.3%). The 4 KiB
OpenTelemetry JSON gains much more, but some other files and packets regress.
Both native references remain faster on the aggregate.

## Changes

The table builder inserts codes of each length once into a populated prefix,
then copies that prefix into its upper half to account for the next bit. This
replaces the old per-symbol strided replication with contiguous copies. The
builder returns the owned lookup buffer directly. The 12-bit table, its entry
encoding, fixed tables and canonical fallback semantics are unchanged.

Dynamic-header lengths now use a 316-byte local array, bounded by the validated
286 literal/length and 30 distance entries. This removes one temporary heap
allocation per dynamic block. Zero-repeat runs advance through already zeroed
bytes; repeat-previous runs fill only their new region. Result, error precedence
and consumed position are checked against the previous growable parser with
canonical bit-at-a-time symbol decoding.

`HuffmanTable::from_lengths` previously overflowed a `u16` count when passed
65,536 nonzero lengths and silently truncated active symbol indices beyond
`u16::MAX`. The regression test reproduced the debug overflow before the fix.
Checked counts and symbol conversion now reject those invalid public inputs
with `InvalidHuffmanTree`. The largest representable symbol still decodes through
canonical fallback. Normal DEFLATE alphabets never reach these bounds.

No new public decoder API, dependencies or unsafe code were added. Dynamic
lookup tables still allocate per block; a reusable decoder context remains
future work. The existing output-buffer APIs benefit from these changes.

## Candidate selection and evidence

Four variants were screened: building a minimal table then replicating it,
growing the table one bit at a time, bounded header storage, and returning the
owned lookup buffer from the builder. The minimal-table attempt regressed on
repository text and was removed. The other changes and the constructor fix form
the final candidate. These combined end-to-end results do not isolate each
change's contribution. All attempts, including the negative result and source
variants, are retained in the
[screening archive](../scripts/reports/library-decode-v4-screening.json.gz).

The final source and binary were frozen before the real-file and expanded
runs and were not retuned afterward. The controller checks that freeze, exact
v3 baseline identity, source/binary stability, packet bytes and native library
hashes. The [v3 source snapshot](../scripts/reports/library-decode-v3-core-sources.json.gz)
preserves the uncommitted baseline sources for reconstruction.

## Paired results

Same macOS arm64 host, Rust 1.88.0, zlib-ng 2.3.3 and libdeflate 1.26. Methods
run serially in rotated order on identical resident packets, charging fresh
output allocation and decoder state inside the timer. Native gzip APIs include
native checksums. File I/O is excluded. Throughput is total raw bytes divided
by summed per-packet median times, not the mean of file throughputs.

| Corpus / format | v3 MB/s | v4 MB/s | Speedup | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Real files / raw | 664.8 | 690.2 | 1.038× | 1027.3 | 1572.1 |
| Real files / gzip | 523.4 | 535.5 | 1.023× | 941.4 | 1541.9 |
| Repository / raw | 942.3 | 1007.4 | 1.069× | 1547.8 | 2425.7 |
| Repository / gzip | 669.4 | 704.9 | 1.053× | 1357.4 | 2353.3 |
| Original synthetic / raw | 16594.3 | 19220.7 | 1.158× | 23497.7 | 21196.0 |
| Original synthetic / gzip | 2173.9 | 2203.0 | 1.013× | 7533.6 | 16965.2 |
| Expanded synthetic / raw | 722.9 | 744.7 | 1.030× | 1015.6 | 1436.6 |
| Expanded synthetic / gzip | 555.6 | 563.3 | 1.014× | 929.9 | 1419.0 |

Raw real-file throughput is still 1.49× behind zlib-ng and 2.28× behind
libdeflate. Gzip is 1.76× and 2.88× behind, respectively. This is progress on
existing diagnostics, not a competitive-release claim.

The real-file roster, pins and inherited license metadata are unchanged from
[v3](library-decode-v3-report.md): Go source, CommonMark text, Inter font,
OpenTelemetry JSON, Kubernetes JSON and Vega weather CSV. These are reused
historical training lineages, 4,134–879,708 bytes, not independent release data.
All are encoded by zlib, zlib-ng and libdeflate at levels 1/6/9 in raw and gzip.
Five sessions yield 2,160 rows over 108 packets and 1,512 rejection checks.

| File | Raw v3 → v4 MB/s | Gzip v3 → v4 MB/s |
| --- | ---: | ---: |
| Go source | 603.1 → 600.6 | 482.0 → 482.2 |
| CommonMark text | 911.4 → 913.6 | 656.6 → 654.0 |
| Inter font | 405.0 → 425.1 | 350.6 → 361.6 |
| OpenTelemetry JSON | 577.7 → 1034.6 | 467.8 → 733.8 |
| Kubernetes JSON | 1872.5 → 1928.9 | 1044.5 → 1061.5 |
| Weather CSV | 829.3 → 889.9 | 619.2 → 651.1 |

OpenTelemetry's raw/gzip gains are 79.1%/56.9%; this single small JSON file
cannot establish a broader small-message workload claim. Per-session real-file
aggregate speedups range from 1.008–1.038× raw and 0.999–1.038× gzip. They
measure repeatability here, not confidence intervals over application workloads.

## Regressions and timing follow-up

The worst real packet is CommonMark gzip encoded by zlib-ng level 1:
343,335 → 365,996 ns (+6.6% time). Tiny raw `hello` from zlib-ng changes from
43.19 to 45.73 ns (+5.9%). Go raw and CommonMark gzip also regress slightly
when aggregated across encoders/levels. No all-input no-regression claim is made.

The expanded run showed a larger anomaly for window-boundary gzip encoded by
zlib-ng level 1: median 648,786 → 815,312 ns (+25.7%). Both versions varied
substantially across its three sessions. A post-hoc investigation repeated
all twelve packets for that source in seven rotated sessions with 100 ms
batches instead of 20 ms. All packet and binary hashes match the originals.
That packet's medians were 508,990 → 515,758 ns (+1.3%); the original magnitude
was not reproduced. This does not erase the original observation or establish
its cause. The original expanded aggregate above is unchanged, and the
[follow-up receipt](../scripts/reports/library-decode-v4-window-followup.json.gz)
retains all 336 additional rows and 168 rejection checks.

Main receipts: [real files](../scripts/reports/library-decode-v4-real.json.gz),
[original diagnostic](../scripts/reports/library-decode-v4.json.gz),
[expanded diagnostic](../scripts/reports/library-decode-v4-expanded.json.gz).
The original and expanded runs contain 840 and 1,152 rows, respectively.
The linked benchmark is 498,096 bytes versus 497,968 bytes for v3 (+128 bytes).
This is not a peak-memory or cross-platform size qualification.

## Correctness and reproduction

Table tests compare every entry with canonical decoding for 2,000 generated
complete trees, fixed tables and degenerate distance trees. New header tests
check exact results and positions across offsets, truncations, repeat overruns,
maximum header dimensions and random malformed headers. Public constructor
bounds are tested in debug and release configurations. These are finite Rust
checks; no new Lean refinement theorem is claimed.

`make test` passes, including the Lean axiom gates, 20,197 differential streams
with zero findings and 1,654 framing checks. All-feature workspace tests,
Clippy with warnings denied, formatting, nine benchmark-evidence tests and
local Cargo package verification pass. Historical source, reference and
decoder receipt audits also pass.
Bounded fuzzing completed 9,514,905 dynamic-header, 6,694,717 inflate, 1,277,322 differential, 183,252 roundtrip runs (46 seconds per target), with no crash discovered.
[Validation logs and source hashes](../scripts/reports/library-decode-v4-validation.json.gz)
retain the evidence, including the pre-fix overflow reproduction.

Use fresh output directories. The same real-file manifest can be reacquired
with `scripts/library_real_corpus.py`; source bodies remain under `target/`.
The controller accepts `--candidate-freeze` to enforce the source/binary freeze
embedded in every final receipt. For a reconstructed binary with a different
hash, record a new freeze rather than rewriting the historical receipt.

```sh
cargo build --locked --release -p deflate-core --example library_decode
python3 scripts/library_bench.py measure --workers target/library-v1/workers \
  --baseline target/library-v4/baseline_decode \
  --baseline-receipt scripts/reports/library-decode-v3.json.gz \
  --candidate-freeze target/library-v4/candidate-freeze.json \
  --corpus-manifest target/library-v3/real-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v4/reproduce-real --sessions 5 --study library-decode-v4-real
python3 scripts/test_library_bench.py
make test
```

Reference acquisition/build instructions remain in the [library plan](library-roadmap.md).
Remaining work includes reusable contexts with fair native reuse comparisons,
independent application corpora, multi-MiB cases, x86-64 and memory measurements.
