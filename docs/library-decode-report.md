# Library decode diagnostic — 2026-10-14

The first library iteration adds reusable output APIs, shares immutable fixed
Huffman tables and uses portable slicing-by-eight CRC32. It improves the old
implementation and wins on two tiny witnesses, but **does not yet match either
native reference on the bulk compressed repository inputs**.

Five rotated serial sessions, 42 packets and four decoders produce 840 timing
rows. Each warm batch runs at least 20 ms with fresh decoder state/output and
resident compressed input. All decoders consume the same packet, emitted by
Python zlib, zlib-ng 2.3.3 or libdeflate 1.26 at level 6, as raw DEFLATE or gzip.
Native gzip timings use actual native gzip APIs and checksums. All decoded
bytes match; 588 truncation, suffix, wrong-size and CRC rejection checks pass.

The host is arm64 macOS 27.2, Rust 1.88.0; exact versions, source/library/binary
hashes and compiler commands are in the [compressed receipt](../scripts/reports/library-decode-v1.json.gz).
This corpus contains two repository files (`Properties.lean` and the DEFLATE
specification), three synthetic 256 KiB inputs and empty/11-byte witnesses.
It is a tuning diagnostic, not an independent or representative release result.
Five sessions measure repetition on this host; no confidence interval or
population generalization is asserted.

## Bulk throughput

MB/s are total uncompressed bytes divided by the sum of per-packet median times.
Scopes are separate. Baseline is the historical decoder-only adapter built at
`03f70cc6de6032f7cc74a0f08c5e45059ee98c90`; candidate uses the public buffer API
with known-size preallocation charged inside the timer. Consequently gains
include API/allocation changes as well as kernel changes.

| Scope / format | Before MB/s | Current MB/s | Change | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Repository / raw | 558.9 | 589.5 | 1.05× | 1610.1 | 2490.7 |
| Repository / gzip | 283.6 | 481.4 | 1.70× | 1410.4 | 2430.6 |
| Synthetic / raw | 12953.0 | 14598.1 | 1.13× | 24815.9 | 22219.2 |
| Synthetic / gzip | 568.0 | 2181.0 | 3.84× | 8003.6 | 17469.9 |

Bulk raw repository throughput is still approximately 2.7× behind zlib-ng and
4.2× behind libdeflate. Gzip remains further behind despite the CRC improvement.
The synthetic aggregate mixes random, periodic and zero data; its high raw
throughput does not describe normal compressed text.

## Tiny witnesses

Mean of the six per-packet median call times (two inputs × three encoders), in
nanoseconds. Fixed tables now avoid per-call table construction and allocation.
These two witnesses establish an optimization effect, not a general small-file
performance claim. Timer overhead is included and not subtracted.

| Format | Before ns | Current ns | zlib-ng ns | libdeflate ns |
| --- | ---: | ---: | ---: | ---: |
| Raw | 2598.5 | 34.0 | 109.5 | 1038.5 |
| Gzip | 2601.0 | 59.8 | 121.7 | 1056.6 |

## Validation and limitations

- `make test`: Rust tests, Lean build/axiom gates, 20,197 streams through three
  oracles with zero findings, and 1,654 framing oracle checks.
- Workspace tests with all features and Clippy with warnings denied pass.
- CRC32 agrees with an independent bitwise reference across offsets, tails and
  incremental chunk sizes. Shared fixed tables equal reconstructed canonical
  tables; the existing table-entry equivalence tests pass.
- API tests cover output reuse, exact raw consumption, output limits, error
  clearing/recovery, truncated gzip and concatenated-member checksum failures.
- Bounded fuzzing: inflate 3,972,041 runs, differential 877,170 runs, roundtrip
  131,178 runs, each 31 elapsed seconds, with no discovered crash.
- `make research-check`, the historical reference/decoder locks and worker
  receipt audit pass. The audit reads the old core from its pinned revision.
- `cargo package --locked -p deflate-core --allow-dirty` packages and verifies
  the library locally. Nothing has been published.

No new Rust-to-Lean refinement proof, x86 benchmark, memory qualification,
reusable native-context comparison or release-quality independent corpus is
claimed. Fixed tables add about 16 KiB of shared lookup data and slicing CRC
uses about 8 KiB of lookup data; linked binary and peak-memory effects remain
release evaluation items. Dynamic Huffman tables use owned heap storage.
The next target is the bulk decoder, with profiling and independent evaluation
specified in the [library plan](library-roadmap.md).
