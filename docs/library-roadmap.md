# Library development: DEFLATE / GZIP

Restarted 2026-10-14 by the maintainer. The first product target is **fast
whole-buffer decompression with an ergonomic Rust API**, compared directly with
zlib-ng and libdeflate. Compression remains available; the cancelled encoder
and DSC1 campaigns are not resumed by this scope.

## Release contract

- Keep raw DEFLATE and gzip interoperability, deterministic errors, explicit
  output limits, and the documented verification boundary.
- Keep `no_std` + `alloc`, zero runtime dependencies and no unsafe code in the
  portable core. No native codec is linked into the library.
- Provide allocating convenience calls and reusable output buffers, with
  explicit consumption and member boundaries. Preserve existing raw suffix
  and gzip concatenation behavior.
- Judge speed against the **same compressed packets**, including state/output
  allocation and native gzip checksums. Evaluate reuse separately for every
  implementation; never compare our reused state against fresh native state.
- A competitive release requires a declared useful workload on which we match
  or beat both references, independent validation beyond tuning inputs, and
  documented tradeoffs on the other workloads. The initial diagnostic does
  not satisfy that release gate.

## Current implementation

`inflate_into` returns consumed/written byte counts and reuses a `Vec`.
`gunzip_into` reuses the first member's output, isolates later member history,
and clears output on failure. The existing wrappers delegate to these paths.
Errors implement the standard Rust error interfaces without adding dependencies.
Fixed Huffman tables are immutable shared tables; CRC32 processes sixteen bytes
per iteration. A proposed wide-load bit reader was slower in diagnostic runs
and was removed. The next iteration adds bounded lookahead for an entire
Huffman/LZ77 token, with exact scalar fallback on misses/short input. See the
[bulk decoder report](library-decode-v2-report.md). The third iteration retains
unused lookahead bits across tokens; its
[real-file diagnostic](library-decode-v3-report.md) includes pinned historical
training sources and per-file tradeoffs. Overflow handling for
skipped-past-end readers was retained.

The fourth iteration grows dynamic Huffman tables through contiguous prefix
copies, constructs the owned lookup buffer in the builder, and uses a bounded
316-byte temporary array for dynamic code lengths. Public Huffman construction
also rejects overflowing counts and unrepresentable symbol indices. See the
[table-construction report](library-decode-v4-report.md). The fifth iteration adds
`Decompressor`, retaining checked dynamic-table allocations and gzip scratch
storage across independent streams. `release_buffers()` releases that working
memory. The [reusable decoder report](library-decode-v5-report.md) compares
fresh calls and state/output reuse separately against both native libraries.
No decoder history crosses calls, including after errors.

The [native source/AST and profile audit](native-decode-audit.md) now ties the
remaining gap to short match copying, per-token bit/output bookkeeping and gzip
CRC. It includes build-specific Clang ASTs, exact-worker profiles, token counts
and isolated CRC measurements. The following
[implementation report](library-decode-v6-report.md) applies those findings:
initialized output batches, fixed-size short copies, packed actions, specialized
table roots and wider portable CRC. Tiny fixed blocks retain the compact decoder.
The [v7 follow-up](library-decode-v7-report.md) profiles that implementation and
loads the next Huffman action before copying a match. Two initial word copies
remove the copy loop for lengths up to sixteen. Paired measurements improve raw
throughput by about 9%; the six-file pool still trails both native references.
The [v8 follow-up](library-decode-v8-report.md) then adapts the native loop's
total-bit actions, groups of literals and byte-cursor bit-buffer refill together.
Raw throughput improves another 19–22% and exceeds pinned zlib-ng by about 7%
on this arm64 development pool. Libdeflate remains 43–45% faster raw, and both
native gzip implementations remain faster. This does not satisfy the independent
evaluation or both-reference release gates.

The [v9 copy follow-up](library-decode-v9-report.md) combines a checked relative
copy region, five initial word copies and a separate small-distance helper.
The final ARM64 continuation is unrolled by LLVM; the whole token function is
smaller than v8. Paired real-pool throughput improves another 4% raw and 3.4%
gzip. The expanded synthetic pool is effectively unchanged, with CSV and tiny
gzip regressions documented. This is still an incremental development result.

The [v10 gzip follow-up](library-decode-v10-report.md) consumes valid headers
without allocating discarded metadata and computes header CRC only for FHCRC.
Malformed/unaligned headers preserve the public parser's exact fallback state.
Short gzip latency improves 28–35%, optional-header examples improve further,
and paired bulk raw throughput regresses about 1%. A dedicated header benchmark
and public-parser differential fuzz target retain that tradeoff and validation.
The [fresh v10 runtime profiles](library-decode-v10-profile.md) expose material
per-call timer overhead on tiny inputs. Batch clock reads consistently across
Rust/native workers before further decoder-only latency claims; prior tiny
results describe instrumented workers. Bulk profiles still prioritize CRC,
token lookup/extraction/copy, and small-stream table/header preparation.

The [v11 CRC backend report](library-decode-v11-crc-accelerator.md) adds the
optional `deflate-accel` crate. It preserves the portable core and routes GZIP
payload checksums through `crc32fast`; in a four-file reused-state diagnostic,
this improved GZIP throughput by 24.5% over the rebuilt core and edged
zlib-ng, while libdeflate stayed ahead. Tiny CRCs can favor the portable path.
Cross-architecture and independent-corpus measurements remain open.

The historical receipt audit now checks the old core against its pinned Git
revision, rather than requiring the current library to equal the old control.
CI fetches that history. Old source hashes and measurement receipts are unchanged.
The historical `new_methods_rust_build.py` must still run from its pinned source
checkout when reconstructing that study; it intentionally rejects current code.

## Next milestones

1. **Decompression foundation:** reusable buffers, native reference harness,
   fixed-table and CRC improvements, correctness and fuzz gates. Implemented;
   measurements are recorded in the [diagnostic report](library-decode-report.md).
2. **Bulk decoder:** a first token lookahead implementation and profile are
   complete, with scalar state-equivalence tests and an expanded synthetic
   check. Bit buffering and a first real-file diagnostic are now implemented;
   two further literal/copy specializations were screened and rejected. Dynamic
   table construction and temporary header storage have also been improved.
   Reusable decoder state and fair native state/output reuse comparisons are
   implemented. Remaining decode/checksum costs have now been profiled against
   the compiled native paths. Bounded output batches, packed entries and
   specialized roots are implemented and measured. Next-action lookahead and
   unrolled short copies are also implemented and measured. Native-style action
   counters, literal grouping and byte-cursor refill are now measured together.
   Copy-region checks and small-distance call-state overhead have now also been
   screened and reduced. Gzip header consumption without metadata allocation is
   implemented and measured. An optional CRC backend is implemented and
   measured on the current arm64 host. A [v12 hot-loop screen](library-decode-v12-report.md)
   rejected three safe match-path reshapings (no paired improvement; one
   compiled identically); next attribute the raw gap with hardware counters
   before writing further candidates. Next investigate the remaining decode
   gap, small-gzip latency, x86-64 behavior, and allocator/peak-memory costs.
   Evaluate whether the optional package boundary should cover more backends.
   Each change must
   preserve exact errors/limits or document an approved
   contract change. Keep scalar/table correspondence tests and Lean differentials.
3. **Independent release evaluation:** licensed application corpora, varied
   encoder levels and block types, malformed data, tiny through multi-MiB inputs,
   both arm64 and x86-64. Measure first call, warm fresh calls, reuse, peak memory
   and linked size. Freeze candidates before independent evaluation; include
   uncertainty and per-file regressions, not only aggregate throughput.
4. **Packaging:** verify an external Cargo consumer and publishable package,
   document API stability and supported targets, and prepare a versioned release
   only after the correctness and performance contract is satisfied.

Streaming, C ABI, preset dictionaries, zlib framing and new compression
algorithms are separate follow-up scopes. A gzip convenience API does not imply
zlib ABI compatibility. The references' APIs and intended use differ:
[libdeflate](https://github.com/ebiggers/libdeflate#api) targets whole buffers;
[zlib-ng](https://github.com/zlib-ng/zlib-ng) also offers a zlib-compatible build.

## Reproduce the first diagnostic

The reference acquisition helper currently targets macOS/clang. These are pinned
references (zlib-ng 2.3.3, libdeflate 1.26), not a promise of latest releases.
Run each output directory once; use a fresh directory for later measurements.
No historical worker directory is replaced.

```sh
python3 scripts/new_methods_references.py --out target/library-v1/references \
  --codec zlib-ng --codec libdeflate \
  --source-lock scripts/reports/new-methods-reference-sources.json
python3 scripts/library_bench.py build --references target/library-v1/references \
  --out target/library-v1/workers
cargo build --locked --release -p deflate-core --example library_decode
python3 scripts/library_bench.py measure --workers target/library-v1/workers \
  --out target/library-v1/run --sessions 5
```

An optional `--baseline PATH` adds the decoder-only historical adapter built
from revision `03f70cc6de6032f7cc74a0f08c5e45059ee98c90`. Build it in an isolated
checkout with `cargo build --locked --release --manifest-path
tools/new-methods-decode/Cargo.toml`; retain the binary before updating sources.
It grows a fresh output buffer; the candidate preallocates the supplied expected
size inside the timer. This before/after comparison includes both API/allocation
and kernel changes, not just an isolated instruction optimization. The baseline
uses the historical canonical gzip adapter; native references use their actual
gzip APIs, including accelerated checksums.

The controller validates packets with Python zlib, runs every decoder on every
packet, rejects truncation/suffix/wrong-size and gzip checksum corruption, rotates
serial method order, and checks exact bytes after every timed batch. It records
source, binary and reference-library hashes, compiler details and all rows.
Its built-in corpus is two repository files, three synthetic regimes and two
short witnesses. This is development evidence; it is not a representative or
independent release benchmark. Tiny-input MB/s is especially misleading; inspect
per-call nanoseconds for those witnesses.
