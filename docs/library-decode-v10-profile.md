# V10 runtime profile follow-up

The v10 implementation was originally evaluated with source/assembly inspection
and paired timings, without a fresh runtime profile. This follow-up fills that
gap and exposes a limitation in the tiny-message timing harness. Production
sources and frozen workers are unchanged.

## Cross-library throughput comparison already performed

The frozen six-file, three-encoder, levels-1/6/9 reused-state pool measures:

| Frame | Core v10 MB/s | zlib-ng 2.3.3 | libdeflate 1.26 |
|---|---:|---:|---:|
| Raw | 1155.0 | 1042.3 | 1598.7 |
| Gzip | 891.7 | 950.4 | 1563.2 |

These come from the unprofiled [v10 receipts](library-decode-v10-report.md).
They show a pooled raw win over zlib-ng, a gzip loss to both references, and
no win over libdeflate. They are development-pool results, not release evidence.

## Fresh exact-worker profiles

24 serial `/usr/bin/sample` runs cover Go, Inter and Otel, raw/gzip, all three
workers, plus empty/hello gzip across all three workers. Each requests two
seconds at 1 ms during a four-second reuse loop. Executable, native-library,
packet and output hashes are checked. The large-case profiles contain
1194–1718 main-thread samples each. Timing under the profiler is not used for
throughput or speedup claims.

| Sampled leaf | Core | zlib-ng | libdeflate |
|---|---:|---:|---:|
| Go raw decode loop | 93.0% | 96.8% | 97.0% |
| Go gzip decode loop | 69.8% | 87.8% | 94.9% |
| Go gzip CRC | **24.5%** | **7.2%** | **2.3%** |
| Inter raw decode loop | 88.7% | 93.7% | 95.9% |
| Inter gzip CRC | 15.0% | 5.6% | 1.1% |

Runtime symbols confirm zlib-ng's `inflate_fast_neon` and `crc32_fold_armv8`,
and libdeflate's `libdeflate_deflate_decompress_ex` and
`crc32_arm_pmullx12_crc_eor3`. Core uses portable `update_slices`. These shares
have different total runtime denominators; their ratios are not absolute cost
ratios. Removing CRC alone would not remove the raw decode gap.

For the small Otel raw case, core samples are 40.1% `decode_tokens`, 17.3%
`peek_bits`, 12.6% `read_dynamic_lengths`, 11.9% `prepare`, and 7.7% external
memmove. Table/header work therefore deserves separate attention for small
dynamic streams. Native table-building leaves account for 34.8% zlib-ng and
41.5% libdeflate; a larger share does not establish larger absolute setup cost.

## Inside the inlined Rust loop

Four additional samply runs use a separate release build with line tables,
with 3973–3998 samples each. Inline resolution now includes `decode_table.rs`
and handles path separators inside generic arguments correctly.

| Inclusive category | Go raw | Inter raw | Go gzip | Otel raw |
|---|---:|---:|---:|---:|
| `decode_tokens` | 92.70% | 88.30% | 67.58% | 40.78% |
| Packed-table lookup | 20.51% | 6.30% | 13.82% | 11.92% |
| Match copying | 18.18% | 6.00% | 12.86% | 7.72% |
| Match-value extraction | 11.51% | 1.10% | 7.43% | 4.60% |
| `peek_bits` | 2.10% | 1.21% | 1.61% | 19.94% |
| CRC slicing | — | — | 26.58% | — |

These categories overlap and omit unresolved inline ancestry. The line-table
build has 1178 instructions in `decode_tokens`, versus 1179 in the exact worker,
and normalized instruction hashes differ. These are supporting source-location
profiles, not exact-binary instruction attribution. A sampled PC at a lookup,
copy or spill is not proof that this operation caused the corresponding stall.
No hardware-counter/PMU attribution is claimed.

## Tiny-message benchmark limitation discovered

The exact-worker tiny profiles show substantial clock-reading cost:

| Gzip case | Core `mach_absolute_time` | zlib-ng | libdeflate |
|---|---:|---:|---:|
| Empty | **66.5%** | 33.0% | 60.7% |
| Eleven-byte hello | **39.4%** | 26.6% | 38.4% |

The workers check elapsed time after each decode. The reported tiny ns/call
therefore includes clock and loop overhead, and Rust/C wrappers are not identical.
The v9→v10 instrumented-worker improvement remains an observed paired result,
but those numbers must not be presented as pure decoder latency or used to
claim decoder-only superiority on tiny inputs. Timer overhead cannot reliably
be subtracted using these sample shares.

The next measurement correction is batching many decode calls between clock
reads, with the same policy across Rust and native workers, output checks and
fresh/reuse contracts retained. That correction has **not** been implemented
or measured in this profiling-only follow-up. It must precede further claims
about nanosecond-level tiny-message competitiveness. Large-buffer results remain
a separate comparison; no speedups are inferred from profiled runs.

## Evidence and next implementation priorities

[scripts/reports/library-decode-v10-profile.json.gz](../scripts/reports/library-decode-v10-profile.json.gz)
archives all 24 sample texts, four raw samply profiles and symbols, resolved
inline PCs, commands, source identities and tooling. Source/worker/native-library
hashes still match the frozen v10 receipt. Previous receipts are unchanged.

After correcting tiny timing, the measured implementation priorities are the
payload CRC backend for large gzip, the lookup/extraction/copy loop for large
raw input, and checked bit reads/table preparation for small dynamic streams.
The gzip-header optimization addresses short framing overhead; it does not
explain or close these remaining bulk gaps.
