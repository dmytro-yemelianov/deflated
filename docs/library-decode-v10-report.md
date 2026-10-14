# Library decode v10: gzip headers without discarded metadata

V10 reduces the latency of short gzip messages by **about 28–35%** in the
reused-state diagnostics and removes metadata allocation for valid aligned
optional headers. Eleven-byte messages with optional fields are **about 4.5–5×
faster than v9** in the generated header diagnostic. Header checksum validation
is preserved. Large-buffer throughput does not improve: pooled raw is about
1% slower, and gzip changes by +0.6% fresh / −0.8% reused. This is a targeted
framing improvement with a measured bulk tradeoff, not an overall decode win.

**Profiling follow-up:** the tiny ns/call figures below include substantial
per-call timer overhead. They are instrumented-worker latency, not isolated
decoder latency. A [fresh runtime profile](library-decode-v10-profile.md) found
39–66% clock samples on the core's hello/empty gzip cases. Batched-clock
remeasurement is required before decoder-only tiny-input superiority claims.

## What the native source revealed

V9's `decode_members` calls the public `read_gzip_header` and immediately drops
its `GzipHeader`. That parser computes a header CRC even when FHCRC is absent
and copies extra/name/comment fields into owned vectors. A decoder that only
needs the payload boundary can avoid that work.

Pinned libdeflate 1.26 `lib/gzip_decompress.c` instead advances through these
fields. It also skips FHCRC verification. V10 adopts boundary-only consumption
while **retaining our stronger FHCRC validation**. The valid-header diagnostic
separately corrupts FHCRC: core v9/v10 and zlib-ng reject all eight variants in
each API mode, while libdeflate accepts them. Thus checksum-bearing native
comparisons do not imply identical validation work.

In [gzip.rs](../crates/deflate-core/src/gzip.rs), a valid aligned minimal header
is handled by magic/method/flags checks and one reader advance. Optional extra
fields use checked length bounds; name/comment fields scan to a real terminator.
CRC is computed only when FHCRC is present. Scanning commits no reader state
until the entire header is validated. Invalid, incomplete, checksum-bad or
unaligned input falls back to the unchanged public parser from the original
position, preserving exact errors and partial consumption. Optional processing
is kept out of the minimal-header path with a separate helper.

The public metadata API, DEFLATE implementation, payload CRC, member isolation,
output clearing on errors, limits and padding behavior are unchanged. The core
remains safe `no_std` + `alloc` with zero runtime dependencies. No allocation
counter or peak-memory measurement is claimed; elimination of owned header
metadata on successful aligned inputs follows directly from this code path.

## Paired short-message measurements

The original seven-case diagnostic retains all three encoders and five rotated
serial sessions. These are the zlib-encoded empty/eleven-byte witnesses, ns/call:

| Mode | Payload | v9 | v10 | zlib-ng | libdeflate |
|---|---|---:|---:|---:|---:|
| Fresh | Empty | 47.2 | 30.5 | 120.1 | 1634.3 |
| Fresh | Hello | 70.6 | 51.6 | 150.6 | 1692.8 |
| Reuse | Empty | 47.0 | 30.2 | 25.0 | 16.8 |
| Reuse | Hello | 67.2 | 48.1 | 53.6 | 27.3 |

An earlier common-header-only screen measured 63.7 → 40.0 ns reused hello.
That was a different source freeze and run; the table above reports the final
optional-field implementation rather than promoting the best exploratory number.

The new [header diagnostic](../scripts/gzip_header_bench.py) covers payloads
0/11/257/4096 and six header forms, for 24 packets per mode. Each uses five
sessions, matching fresh/reused workers, verified freezes and at least 20 ms
per timing batch. Python zlib independently validates every generated packet.
All outputs are checked and the exact packet bytes are archived. Representative
**reuse** results, ns/call:

| Eleven-byte payload header | v9 | v10 | zlib-ng | libdeflate |
|---|---:|---:|---:|---:|
| Minimal | 64.7 | 42.3 | 49.6 | 24.9 |
| Extra field, 64 bytes | 228.5 | 45.2 | 51.9 | 26.2 |
| Name/comment, 64 bytes each | 397.6 | 80.0 | 86.0 | 64.8 |
| Extra/name/comment + FHCRC, 64 bytes each | 587.4 | 119.7 | 106.7 | 62.4 |
| Extra/name/comment + FHCRC, 8192 bytes each | 54364.1 | 11745.3 | 6386.0 | 4094.3 |

The separate run confirms the minimal-header improvement, with absolute rates
varying between runs. The largest header is still substantially slower than
both native implementations. These deliberately generated development inputs
are not representative traffic frequencies or an independent holdout.

## Bulk regression checks

The same six real files × three encoders × levels 1/6/9 give 108 raw/gzip
packets. Five serial sessions compare frozen v9/v10 and unchanged native workers.
Pooled rates use bytes divided by summed per-packet median times.

| Mode | Frame | v9 MB/s | v10 MB/s | zlib-ng | libdeflate |
|---|---|---:|---:|---:|---:|
| Fresh | Raw | 1162.2 | 1152.3 | 1035.0 | 1581.6 |
| Fresh | Gzip | 889.0 | 894.5 | 945.3 | 1560.2 |
| Reuse | Raw | 1166.9 | 1155.0 | 1042.3 | 1598.7 |
| Reuse | Gzip | 899.0 | 891.7 | 950.4 | 1563.2 |

Every raw session is slower than its paired v9 baseline; this is not presented
as a bulk improvement. Raw session ratios range 0.953–0.992 fresh and
0.978–0.997 reused. Gzip is noisier: 0.918–1.022 fresh and 0.752–1.007 reused.
Worst individual packet median ratios are 0.939/0.935 raw and 0.961/0.859 gzip
(fresh/reuse). The payload source is unchanged, but this study does not establish
the cause of layout or timing effects. All measurements are retained.

The expanded synthetic pool changes 1177.2 → 1170.2 MB/s raw and
887.5 → 878.9 MB/s gzip. Its separate small-input group improves gzip
1038.0 → 1305.2 MB/s. Whole benchmark executables grow by 288 bytes fresh
and 272 bytes reused; these are not isolated linked-library sizes.

## Correctness and reproducibility

New tests compare skipped headers against the public parser for all 32 valid
flag combinations, offsets 0–7, every truncation of short headers, mutations,
all byte values in the fixed header, 65535-byte extra fields, 8192-byte strings
and past-end reader positions. A new `gzip_header` fuzz target checks independent
public-parser rejection and uses its accepted boundary to construct an empty
DEFLATE member for fresh and reused APIs. Its initial corpus includes every
valid flag combination and deliberately corrupted FHCRC seeds.

All gates passed: `make test` (Rust, Lean axiom gate, 20,197 streams against
three oracles with zero findings, and 1654 framing checks), all workspace
features, clippy with warnings denied, formatting, Cargo package verification,
and 17 receipt-integrity tests. Six fuzz targets each completed 31 seconds,
for **16,929,411 executions** without crash or disagreement; the new
header target contributed 4,426,587 executions.
Frozen source and worker hashes were rechecked after validation. The graph was
refreshed to 1491 nodes / 5834 edges without writing a shared graph artifact.

Ten immutable `scripts/reports/library-decode-v10*.json.gz` artifacts retain
five standard receipts (7728 timed rows, 6216 rejection checks), two header
receipts (960 additional timed rows, 64 FHCRC contract checks), the complete
source snapshot, source/assembly screening evidence and validation logs. The
screening archive includes the selection/analysis controllers; the header
receipts embed their controller source and packets. Source and worker hashes
are checked before and after timing. No retained timing runs overlap builds,
tests, profilers or fuzzing. V1–v9 receipts/native pins are unchanged; the v9
prose's fresh executable-size delta was corrected to match its existing receipt.

This work does not close the raw gap to libdeflate or the large-gzip checksum
gap. Independent corpora, x86-64, memory measurements and the both-reference
release gate remain outstanding. Header/parser correspondence is tested, not
formally proved by the Lean framing model.
