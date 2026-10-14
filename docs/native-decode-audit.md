# Native decoder source and profile audit

The v5 gap is primarily in the Huffman/LZ77 loop: short match copying, bit-buffer
bookkeeping and output handling. Gzip adds a substantial portable CRC cost.
Larger Huffman lookup tables alone are unlikely to close the gap. This audit
changes diagnostic tooling and documentation; production decoder sources still
match the frozen v5 receipt.

The existing [v5 reused-state measurement](library-decode-v5-report.md) is the
performance baseline, in decimal MB/s on this arm64 host:

| Real-file pool | Core | zlib-ng | libdeflate |
|---|---:|---:|---:|
| Raw DEFLATE | 707.8 | 1045.5 | 1607.4 |
| Gzip | 550.1 | 956.1 | 1569.1 |

That is a raw throughput gap of 1.48× / 2.27× and a gzip gap of 1.74× / 2.85×.
The profiles below explain where to investigate; they are not new throughput
benchmarks or measured speedups from individual proposed changes.

## Sources and the actual compiled AST

Both native source trees were already retained beside their benchmark builds:

| Reference | Local source | Verified archive SHA-256 |
|---|---|---|
| zlib-ng 2.3.3 | [source](../target/library-v1/references/zlib-ng/source/) | `f9c65aa9c852eb8255b636fd9f07ce1c406f061ec19a2e7d508b318ca0c907d1` |
| libdeflate v1.26 | [source](../target/library-v1/references/libdeflate/source/) | `bba03fffc5538576213675ce6968fcff6ce2e67d82e4d5febea2d05f9f13cf85` |

All 355 zlib-ng and 94 libdeflate regular source files matched those archives.
Installed dylibs matched the original build receipts. These are pinned versions,
not a claim about the latest available releases.

Codebase-memory graph discovery found the relevant functions and templates, but
macro expansion and conditional dispatch exceeded its precision: the source graph
traced libdeflate through an x86 selector even on this ARM build. Consequently,
`scripts/native_decode_ast.py` replays the **recorded compiler defines, include
paths and target** with `-fsyntax-only -Xclang -ast-dump=json`. Eight translation
units cover inflate, table construction, dispatch, ARM copies, gzip and CRC.
The compiler is Apple Clang 21.0.0; native builds use `-O3 -DNDEBUG`.

The expanded AST confirms `inflate_fast_neon` for zlib-ng and the default
64-bit-word decoder for libdeflate on this build. Sampled runtime symbols confirm
the paths actually exercised. In particular, the libdeflate inflater here is
not the BMI2 decoder. AST call sites and syntax counts are structural evidence,
not executed frequencies; macro `do/while (0)` nodes are not expensive runtime
loops merely because an AST counts them.

## What the implementations do differently

| Area | Current Rust core | Native source findings |
|---|---|---|
| Loop boundaries | One token at a time; refill below 42 available bits; commit a saturating bit position per token | Guard enough input/output for a fast region, keep pointer/bit state local, then use a checked tail |
| Literals | Individual `Vec::push` and output-limit checks | Decode up to three literals per fast iteration; amortize boundary checks |
| Match copy | Lengths below 16 use checked byte reads and `Vec::push`; longer matches use `extend_from_within` | zlib-ng copies 16-byte NEON chunks; libdeflate uses machine-word copies and specialized short-distance patterns |
| Decode entries | A `u16` stores symbol and code length; length/distance bases and extra counts require separate arrays | Entries encode the decoding action, base and bit counts; libdeflate packs these into 32 bits |
| Table layout | Three 4096-entry lookup allocations, 24,576 bytes excluding other state | Specialized roots and subtables; libdeflate overlays temporary table storage and has 10,976 bytes of maximum litlen/offset entry storage |
| CRC | Portable slicing-by-8 | ARM CRC instructions and, in the sampled libdeflate backend, PMULL/EOR3 folding |

Read the core paths in [block.rs](../crates/deflate-core/src/block.rs),
[lz77.rs](../crates/deflate-core/src/lz77.rs),
[bitstream.rs](../crates/deflate-core/src/bitstream.rs) and
[huffman.rs](../crates/deflate-core/src/huffman.rs).

For zlib-ng, [inffast_tpl.h](../target/library-v1/references/zlib-ng/source/inffast_tpl.h)
contains the loop and
[chunkset_neon.c](../target/library-v1/references/zlib-ng/source/arch/arm/chunkset_neon.c)
instantiates the 16-byte copy implementation. Its dynamic roots are **10 literal/
length bits and 9 distance bits**, with 7 for the code-length alphabet; these
are this version's choices, not the often quoted vanilla-zlib defaults. The
builder can reduce a root width to the actual maximum code length.

For libdeflate,
[deflate_decompress.c](../target/library-v1/references/libdeflate/source/lib/deflate_decompress.c)
defines packed entries and maximum roots of 11/8/7 bits for literal-length,
offset and precode. Maximum entry counts are 2342/402/128. Its
[decompress_template.h](../target/library-v1/references/libdeflate/source/lib/decompress_template.h)
preloads the next decode entry before copying a match. With offset at least
eight, the fast copy writes five machine words (40 bytes on this host) before
any continuation. The fast-loop output guard accounts for up to 299 bytes,
including overcopy slack. Boundary paths retain safety checks.

This does not translate directly into writing beyond a Rust `Vec`'s length:
capacity alone is not an initialized mutable slice. A safe adaptation needs an
initialized output region, a cursor and explicit bounds, with any initialization
cost included in measurements. Neither native implementation's checks should be
described as simply disabled.

## Profiles: the loop dominates larger inputs

Eighteen serial `/usr/bin/sample` runs covered Go, Inter and the 4 KiB Otel case,
raw and gzip, across all three exact frozen v5 workers. Each sampled two seconds
of a four-second reused-state/output loop using the same zlib-level-6 packet.
All output hashes matched. Denominators include all main-thread samples,
including leaves omitted by `sample`'s display threshold.

| Core packet | Block-loop leaf | Gzip-wrapper leaf, including inlined CRC | Other notable leaves |
|---|---:|---:|---|
| Go raw | 95.0% | — | memmove 3.4% |
| Inter raw | 92.7% | — | memmove 3.6% |
| Go gzip | 72.8% | 23.5% | memmove 2.3% |
| Inter gzip | 80.3% | 14.0% | memmove 2.3% |
| Otel raw | 48.5% | — | peek_bits 11.2%; dynamic lengths 10.9%; prepare 8.2%; rebuild 3.1%; memmove 14.3% |

`memmove` includes both table replication and match copying; it cannot all be
charged to LZ77. Header/table work is material for small messages, but the
larger-input profiles do not point to allocation or table setup as the main
remaining bottleneck. Native Otel table-building leaf shares are 37.4% for
zlib-ng and 41.5% for libdeflate. Those relative shares do not imply greater
absolute table-building cost: a faster decode loop raises the setup fraction.

A separate release build with line tables resolves inlining more precisely:

| Identifiable inclusive category | Go raw | Inter raw | Go gzip |
|---|---:|---:|---:|
| `decode_huff_block` | 94.30% | 91.59% | 70.58% |
| `copy_back` | 33.99% | 13.06% | 24.27% |
| `peek_word` | 3.49% | 10.69% | 2.70% |
| `skip_bits` | 1.03% | 4.74% | 1.35% |
| CRC `update` | — | — | 24.52% |

These categories **overlap**: copying and bit operations occur inside the block
loop. Missing inline ancestry also prevents treating the copy figures as exact
total copy costs. There are 3980/4005/4001 samples respectively. The corrected
attribution retains a physically qualified core function when debug information
points to `std/mod.rs:0`; treating such PCs as outside the core would be wrong.

The exact v5 and line-table builds have the same 723-instruction block-loop
structure after normalizing relocations and Rust symbol hashes. One Go raw PC
accounts for 27.24% of samples at a shared stack-state reload and branch back to
the loop; other hot PCs fall in the byte-copy loop. This motivates investigating
state spills and dependencies. It does **not** establish that a particular load
caused 27% of stalls: no hardware stall/cycle counters were collected.

## Token census: short copies are common, long codes are rare

The untimed `decode_shape` example uses canonical symbol decoding, records
length/distance histograms and checks bytes/consumption against the normal core
decoder. Python zlib independently checks the packet's expected output hash.
All 54 raw packets passed: six files, three encoders, three levels. The following
ratios pool counts over nine encodings per file, rather than averaging percentages.
They therefore differ in scope from the single zlib-level-6 profiles above.

| File | Matches shorter than 16 | Output bytes from those matches | Literal share of tokens | Huffman codes longer than 12 bits | Matches with distance ≥8 |
|---|---:|---:|---:|---:|---:|
| CommonMark | 84.4% | 45.3% | 41.0% | 0.1310% | 99.1% |
| Go | 93.1% | 70.7% | 36.2% | 0.0665% | 99.8% |
| Inter | 92.7% | 40.5% | 80.2% | 0.0236% | 87.9% |
| Kubernetes | 77.5% | 18.3% | 39.9% | 0.0352% | 99.6% |
| Otel | 55.2% | 15.3% | 67.4% | 0% | 95.1% |
| Vega weather | 92.7% | 82.7% | 25.3% | 0.0451% | 99.7% |

Our bytewise path consequently handles most matches and much of the output on
several files. Native word copies apply to a large fraction of distances.
Optimizing rare codes above 12 bits is a lower priority; this census does not
count short-input fallback frequency, so it does not establish that all scalar
fallback is negligible.

## CRC is a separate gzip cost

CRC-only timers used the six resident uncompressed files, warm dispatch, five
rotated serial sessions and 100 ms batches. All 90 results matched Python zlib.
Pooled throughput is total file bytes divided by the sum of per-file median
times; input I/O and allocation are outside the timer.

| Implementation | CRC-only GB/s |
|---|---:|
| Portable core | 2.54 |
| zlib-ng | 11.30 |
| libdeflate | 89.20 |

These are cache-resident checksum rates on this machine, not streaming DRAM
bandwidth or whole-gzip speedups. Samples identify zlib-ng's
`crc32_fold_armv8` and libdeflate's `crc32_arm_pmullx12_crc_eor3`; source dispatch
and Clang AST support those selections. See
[zlib-ng ARM CRC](../target/library-v1/references/zlib-ng/source/arch/arm/crc32_armv8.c)
and [libdeflate ARM CRC](../target/library-v1/references/libdeflate/source/lib/arm/crc32_impl.h).
Accelerating CRC can remove a substantial gzip cost, but cannot close the raw
DEFLATE gap.

The framing contracts also differ: libdeflate's gzip wrapper skips FHCRC instead
of validating it; our API validates optional header CRC and handles concatenated
members. These packets have one member and no optional header fields, so those
contract differences do not explain this measured gap.

## Ranked implementation experiments

1. **A safe bounded output region and batch decode loop.** Hoist boundary checks,
   keep cursor/bit state local and replace common short byte copies with bounded
   bulk copies. Preserve overlap semantics, exact limits, consumed bytes and
   scalar error/tail behavior. Measure initialized-buffer cost in fresh calls as
   well as reuse. Keep `no_std`, zero dependencies and `forbid(unsafe_code)`.
2. **Packed decode actions and specialized table roots.** Test fewer dependent
   loads and smaller table working sets alongside the loop changes. This is an
   experiment, not a guaranteed win from doubling entry size. Earlier isolated
   wide-read and literal/copy specializations regressed and were rejected.
3. **A CRC backend design.** Hardware intrinsics or a separate audited backend
   need an explicit architecture compatible with the portable core contract;
   do not silently introduce unsafe code into it.
4. **Small-message header/table cost.** Optimize construction and temporary
   storage separately, with latency measurements. This cannot explain away the
   larger-input loop gap.

Screen changes individually on frozen packets, then run correctness, differential
and fuzz gates and independent corpus/architecture evaluation as described in the
[roadmap](library-roadmap.md). AST structure and sampled profiles rank candidates;
only controlled before/after measurements can establish their speedups.

## Evidence and reproduction

The portable evidence bundle is
[`native-decode-audit.json.gz`](../scripts/reports/native-decode-audit.json.gz).
It retains archive/file/build hashes, graph findings, compiled AST inventories
and commands, all 18 sample texts, three raw samply profiles, resolved inline PC
chains, core assembly comparison, all census/CRC rows and validation logs. The superseded inline
attribution from the initial helper is omitted; commands are retained and the
corrected attribution is authoritative. Full compiler AST JSON,
native assembly and dSYM remain in `target/native-audit/`; their hashes
and/or generating commands are recorded. Target paths are local artifacts and
must be reconstructed after cleaning the build directory.

With the pinned references, packets and v5 workers from the v5 report available,
run these separately, with no concurrent builds or tests during timers. Each
output directory must be new:

```sh
python3 scripts/native_decode_ast.py --references target/library-v1/references --out target/native-audit-rerun/ast
python3 scripts/native_decode_profile.py --out target/native-audit-rerun/profiles
cargo build --locked --release -p deflate-core --example decode_shape --example crc_bench
python3 scripts/native_decode_diagnostics.py --out target/native-audit-rerun/diagnostics
CARGO_PROFILE_RELEASE_DEBUG=line-tables-only CARGO_TARGET_DIR=target/native-audit-rerun/profiling cargo build --locked --release -p deflate-core --example library_decode_reuse
dsymutil target/native-audit-rerun/profiling/release/examples/library_decode_reuse
```

For inline profiles, replay each recorded `samply record` command with the new
binary/output paths, then pass the three resulting `.json.gz` profiles to
`scripts/native_inline_attrib.py --binary BINARY --out attribution.json`.
The exact original recording script is included in the evidence bundle.

Validation: four tooling unit tests, the 54-packet census, 90 CRC checks, output
hash checks for all 21 sampled runs, examples Clippy with warnings denied,
formatting and whitespace checks passed. Frozen v5 source and native library
hashes were checked again. Production Rust/Lean/fuzz gates remain the v5 results;
they were not rerun for this diagnostic-only change.
