# Library decode v9: checked match-copy regions

V9 improves the six-file arm64 development pool by **4.1–4.3% raw** and
**3.4% gzip** relative to the frozen v8 binaries. Raw throughput is now about
11% above pinned zlib-ng 2.3.3; libdeflate 1.26 remains 37% faster raw. The
expanded synthetic pool is essentially unchanged. CSV packets and tiny gzip
calls include regressions. These are tuning inputs, not independent release
qualification or a claim across architectures.

## Source and machine-code changes

The [native source/AST audit](native-decode-audit.md) identifies libdeflate's
five initial machine-word copies and its hoisted input/output guards. The
[v8 investigation](library-decode-v8-report.md) also showed that removing
checks alone can regress throughput. V9 tests the remaining copy differences
against v8, retaining the original sources, binaries and receipts.

In [block.rs](../crates/deflate-core/src/block.rs), the distance-at-least-eight
path now expresses both source and destination relative to one checked output
region. Five unconditional eight-byte copies cover short matches; a continuation
handles longer ones. Distances below eight use a separate, non-inlined helper
with the existing fill/prefix-expansion algorithm. That helper is not marked
cold: repetitive inputs still exercise it heavily.

The actual ARM64 build has two bounds branches before the initial copies,
versus six before v8's first two copies. Separating the helper removes stores
of loop state from the common match branch. **Some stack loads remain.** LLVM
fully unrolls the final continuation again; it does not preserve a compact
machine-code loop. However, the complete `decode_tokens` body has 1179
instructions versus v8's 1248. This combined result is faster; it does not
establish that unrolling by itself is beneficial or attribute a percentage of
stalls to bounds checks. No PMU stall measurement is claimed.

The core remains safe `no_std` + `alloc` with zero runtime dependencies. The
264-byte initialized-output guard is unchanged. Five initial words can write
37 speculative bytes after a three-byte match. Those bytes are outside logical
history until overwritten by later tokens, and are truncated before return.
Copies proceed in order so distances eight through thirty-nine expand their
own newly produced history correctly. Table layout, refill, allocation strategy,
CRC, public APIs, exact error positions and suffix/member behavior are unchanged.

## Exploratory screens

Each screen uses the same six real files, three encoders at level 6, and three
rotated serial sessions. Results are cumulative variants, not additive effects.

| Variant | Raw throughput relative to v8 |
|---|---:|
| Relative region, bounded variable-trip word loop | 1.013× |
| Original copies, separate small-distance helper | 1.023× |
| Relative loop plus helper | 1.021× |
| Five initial words, bounded variable-trip loop, helper | 1.029× |
| Five initial words, simple while continuation, helper | 1.031× |

The bounded variable-trip loop avoids full unrolling but introduces vector-loop
setup and rounding work. The final while form avoids that setup and is unrolled
by LLVM. Selection used separate final measurements below, after comments and
expanded copy-boundary tests were frozen.

## Final paired measurements

Six pinned files × three encoders × levels 1/6/9 × raw/gzip give 108 packets.
Five sessions rotate all four decoders serially, with at least 20 ms per batch
and exact output validation. Fresh and reused state/output are compared in
matching modes, including native gzip checksum work. Pooled throughput divides
bytes by summed per-packet median times; it is not an average of MB/s values.

| Mode | Frame | v8 MB/s | v9 MB/s | zlib-ng | libdeflate | v9/v8 |
|---|---|---:|---:|---:|---:|---:|
| Fresh | Raw | 1107.8 | 1155.6 | 1034.1 | 1579.0 | 1.043× |
| Fresh | Gzip | 860.1 | 889.7 | 945.8 | 1552.8 | 1.034× |
| Reuse | Raw | 1115.1 | 1160.4 | 1044.1 | 1595.0 | 1.041× |
| Reuse | Gzip | 868.7 | 897.9 | 954.9 | 1567.9 | 1.034× |

All sessions improve over v8: 3.3–4.5% fresh raw, 3.4–6.5% reused raw,
1.9–3.6% fresh gzip, and 2.4–5.0% reused gzip. Absolute host rates vary between
studies; compare paired workers here, not v9 against v8's earlier absolute rates.
An initial final-run attempt started before the preceding build completed. It
was stopped, marked invalid, and excluded. All retained final runs began after
the build completed and used verified source/binary freezes; no builds, tests,
profilers or fuzzers ran concurrently with those timers.

| File | Fresh raw v9/v8 | Reused raw v9/v8 |
|---|---:|---:|
| CommonMark | 1.033× | 1.003× |
| Go | 1.020× | 1.024× |
| Inter | 1.037× | 1.036× |
| Kubernetes | 1.126× | 1.111× |
| Otel | 1.021× | 1.017× |
| Weather CSV | 0.967× | 0.993× |

Worst individual raw packets regress 8.4% fresh and 7.5% reused; worst gzip
packets regress 3.2% and 3.5%. The expanded development families remain nearly
flat: 1180.2 → 1181.6 MB/s raw and 887.6 → 888.5 MB/s gzip. Numeric CSV raw
regresses 1.7%; JSON raw improves 3.6%. This is not an unseen holdout.

For the zlib-encoded eleven-byte hello witness, fresh raw changes 42.6 → 40.8
ns and fresh gzip 63.7 → 63.9 ns. Reused raw changes 35.6 → 35.9 ns, but reused
gzip regresses **60.1 → 65.0 ns**. Empty reused gzip changes 41.9 → 42.9 ns.
Tiny inputs do not use this match loop; executable-layout effects are possible,
but this study does not establish their cause. Whole benchmark executable size
increases by 64 bytes fresh and 96 bytes reused; this is not isolated linked-library size.

## Validation and evidence

The existing bytewise-history tests cover every match length 3–258. Distances
now include every value 1–41 and boundaries 63/64/65, 255/256 and 32768. Poisoned
padding and an outer sentinel check history expansion and the 264-byte guard.
Existing differential tests cover all bit offsets, truncated streams, long-code
fallback, limits, exact errors/positions/partial output, reused state and framing.

All gates passed: `make test` (Rust, Lean axiom gate, 20,197 streams against
three oracles with zero findings, and 1654 framing checks), all workspace
features, clippy with warnings denied, formatting, local Cargo package
verification, and 15 receipt-integrity tests. Five fuzz targets (`reuse`,
`inflate`, `dynamic_header`, `differential`, `roundtrip`) each ran for 31 seconds,
completing **13,102,103 executions** with no crash or disagreement.
Frozen source and executable hashes were rechecked after validation. The graph
was refreshed to 1484 nodes and 5772 edges; no shared graph artifact was written.

The immutable archives under `scripts/reports/library-decode-v9*.json.gz`
retain five final receipts (7728 timed rows, 6216 rejection-contract checks),
the complete source snapshot, five source-verified screens with ARM64 assembly,
and validation logs. V1–v8 evidence and native pins are unchanged. The screening
archive includes the exact final-run controller and analysis script; frozen
baseline binaries are in `target/library-v9/baseline-{fresh,reuse}`. Historical
receipt tests verify source hashes, matching mode baselines, packet identity,
complete pairs and recomputed aggregates.

Remaining work includes the raw gap to libdeflate, small-gzip latency, optional
hardware CRC design, independent corpora, x86-64 and memory measurements. No
Rust refinement proof or competitive-release gate is claimed by these finite
checks or this performance result.
