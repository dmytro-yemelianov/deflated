# Reusable decoder allocations — 2026-10-14

The fifth iteration adds `Decompressor` for repeated whole-buffer raw DEFLATE
and gzip decoding. It retains dynamic Huffman working tables and gzip member
scratch storage, while callers retain their output `Vec`. The library remains
`no_std` + `alloc`, dependency-free at runtime and free of unsafe code.

```rust
use deflate_core::{Decompressor, Error};

fn decode_many(packets: &[&[u8]]) -> Result<(), Error> {
    let mut decoder = Decompressor::new();
    let mut output = Vec::new();
    for packet in packets {
        decoder.inflate_into(packet, &mut output, 64 * 1024)?;
        // Consume output before the next call replaces it.
    }
    decoder.release_buffers();
    Ok(())
}
```

## Contract and memory

`new()` allocates nothing. Dynamic blocks allocate three lookup tables lazily;
subsequent headers rebuild every entry and reuse the existing allocations.
After dynamic decoding, table storage is about 25 KiB plus allocator overhead.
Gzip may retain an additional member buffer, and optional header fields still
allocate per member. No allocation-free or measured peak-memory claim is made.
`release_buffers()` frees working buffers without changing caller output.
Limits bound decoded length, not previously retained capacity.

Every call starts an independent stream, including after errors. Output is
cleared before decoding and after failure. Raw returns consumed/written counts
and accepts a suffix after the final byte; gzip validates all members, their
checksums, cumulative limits and trailing padding. This is a whole-buffer API;
there is no incremental streaming or persistent dictionary.

## Measurement boundary

Fresh calls and reuse have separate executable adapters. Fresh calls charge
state/output allocation and destruction inside each timed iteration. Reuse
charges state initialization and output allocation to the recorded first call;
warm iterations retain both state and output for **every** implementation.
zlib-ng uses `inflateReset`, and libdeflate retains its decompressor object.
Native gzip calls include native checksums. Rebuilding tables and validating
input remain timed. File I/O is outside both timers.

The fresh Rust adapter is byte-identical to v4's source. Early screens combined
fresh and reuse modes in one executable and showed about 8–11% lower repository
raw throughput. Restoring the original adapter while keeping the new core
removed that difference in a follow-up screen. Changing inlining, restoring the
old block driver and moving output I/O did not resolve it. This establishes
adapter/binary sensitivity, not a proven hardware or compiler cause. The final
adapters separate the modes; their results do not isolate allocation savings
from all binary-layout effects. All eight screens, including negative results,
source variants and the exploratory profile are retained in the
[screening archive](../scripts/reports/library-decode-v5-screening.json.gz).

All final runs use the same frozen core sources. Each adapter has its own binary
freeze, checked before and after timing. The exact archived v4 binary is the
fresh baseline; [its source snapshot](../scripts/reports/library-decode-v4-core-sources.json.gz)
retains the uncommitted source state. Native versions remain pinned zlib-ng
2.3.3 and libdeflate 1.26, on macOS arm64 with Rust 1.88.0. Methods run serially
in rotated order, without our tests/builds/fuzzing running concurrently. Other
host applications were not isolated; absolute rates are local diagnostics.

The six real files and their pins/licenses are unchanged from
[v3](library-decode-v3-report.md): Go source, CommonMark, Inter, OpenTelemetry
JSON, Kubernetes JSON and weather CSV. They are historical **training** sources,
4,134–879,708 bytes, not independent release data. Three encoders at levels
1/6/9 produce 108 packets. Each warm batch repeats one resident packet; these
measurements do not establish heterogeneous-stream or streaming throughput.
The builtin corpus adds 42 repository/synthetic/tiny packets.

Throughput is total raw bytes divided by summed per-packet median times across
five sessions. Each decoder sees byte-identical packets. Fresh and reuse rows
are never pooled. The harness rejects mixed contexts and audits hashes, exact
output, consumption, truncation, wrong size, suffixes and gzip checksum errors.

## Results

On the six real files, fresh-call performance is close to v4: raw decreases
0.3% and gzip 1.2%. This iteration is primarily an API/allocation milestone.

| Real files, fresh calls | v4 MB/s | v5 MB/s | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: | ---: |
| Raw | 685.1 | 682.8 | 1021.9 | 1554.4 |
| Gzip | 537.1 | 530.6 | 937.3 | 1539.9 |

| Real files, reused state and output | v5 MB/s | zlib-ng MB/s | libdeflate MB/s |
| --- | ---: | ---: | ---: |
| Raw | 707.8 | 1045.5 | 1607.4 |
| Gzip | 550.1 | 956.1 | 1569.1 |

Reuse raw remains 1.48× behind zlib-ng and 2.27× behind libdeflate; gzip remains
1.74× and 2.85× behind. Relative to the separately measured fresh v5 adapter,
observed reuse rates are about 3.7% higher in both formats. These are different
executables and serial runs, so this is not an isolated allocation-cost estimate.

| File | Fresh v5 raw / gzip MB/s | Reuse v5 raw / gzip MB/s |
| --- | ---: | ---: |
| Go source | 602.5 / 478.0 | 637.0 / 496.9 |
| CommonMark | 899.5 / 640.1 | 946.3 / 680.0 |
| Inter font | 419.5 / 357.6 | 430.7 / 369.3 |
| OpenTelemetry JSON | 1023.9 / 730.7 | 1128.4 / 779.8 |
| Kubernetes JSON | 1911.2 / 1062.3 | 2019.1 / 1101.8 |
| Weather CSV | 879.9 / 648.9 | 927.1 / 673.8 |

Fresh real-file per-session v5/v4 speed ratios range from 0.974–1.003 raw and
0.984–1.002 gzip. The worst real raw packet is CommonMark/zlib level 6:
196,173 → 211,804 ns (+8.0% time). The worst gzip packet is Go/libdeflate level 9:
477,562 → 518,830 ns (+8.6%). No all-input no-regression claim is made.

The builtin run was more variable: repository raw is 790.8 → 775.4 MB/s,
while gzip is 538.4 → 641.5 MB/s. That large gzip difference is not presented as
a demonstrated optimization. The sources were not retuned after these results.

Tiny witnesses illustrate why native reuse must be measured too. For the single
11-byte `hello world` packet encoded by zlib, median warm times are:

| Mode / format | v5 ns | zlib-ng ns | libdeflate ns |
| --- | ---: | ---: | ---: |
| Fresh / raw | 46.7 | 155.7 | 1771.8 |
| Reuse / raw | 38.3 | 38.7 | 22.5 |
| Fresh / gzip | 91.6 | 155.8 | 1706.5 |
| Reuse / gzip | 58.9 | 53.7 | 27.2 |

These short, timer-sensitive witnesses do not establish a small-message workload
claim. Native state reuse removes most of the fresh-call allocation penalty.

Receipts: [fresh real](../scripts/reports/library-decode-v5-real.json.gz),
[reuse real](../scripts/reports/library-decode-v5-reuse-real.json.gz),
[fresh builtin](../scripts/reports/library-decode-v5.json.gz),
[reuse builtin](../scripts/reports/library-decode-v5-reuse.json.gz).
Together they contain 5,250 timed rows and 3,675 rejection checks. Packet hashes
match between modes; native build identities and all core sources match too.
The [v5 source snapshot](../scripts/reports/library-decode-v5-core-sources.json.gz)
preserves the final code and both adapters.

## Correctness and reproduction

Tests compare fresh/reused outputs and exact results through mixed raw/gzip
calls, multi-block streams, limits, truncations, errors, explicit buffer release
and subsequent recovery. Huffman tests alternate complete, empty, degenerate
and invalid trees, checking all entries and stable allocation addresses.
Independent contexts also remain `Send + Sync`. The new `reuse` fuzz target
retains a context across fuzz inputs and compares it with fresh calls.

`make test` passes: Rust tests, Lean axiom gates, 20,197 differential streams
with three oracles and zero findings, and 1,654 framing checks. All-feature
workspace tests, Clippy with warnings denied, formatting, local Cargo package
verification and historical receipt/reference audits pass. Eleven benchmark
evidence tests audit frozen identities, source snapshots, complete pairs and
separation of fresh/reuse contexts.

Bounded fuzzing found no crash or disagreement in 5,118,907 reuse,
8,641,251 dynamic-header, 6,409,832 inflate, 1,133,219 differential and 134,323
roundtrip runs (46 seconds each; 21,437,532 total). These are finite checks,
not proof of bug absence. [Validation logs and source hashes](../scripts/reports/library-decode-v5-validation.json.gz)
retain the evidence.

```sh
cargo build --locked --release -p deflate-core \
  --example library_decode --example library_decode_reuse
python3 scripts/library_bench.py build --references target/library-v1/references \
  --out target/library-v5/reproduce-workers
python3 scripts/library_bench.py measure --reuse \
  --workers target/library-v5/reproduce-workers \
  --corpus-manifest target/library-v3/real-corpus/manifest.json --levels 1 6 9 \
  --out target/library-v5/reproduce-reuse --sessions 5
python3 scripts/test_library_bench.py
make test
```

Use new output directories. Reference acquisition is described in the
[library plan](library-roadmap.md); `library_real_corpus.py` reacquires the
pinned historical training files. Add `--candidate-freeze` for the source/binary
freeze being evaluated. To repeat the fresh comparison, omit `--reuse` and
supply the archived v4 `--baseline` and `--baseline-receipt`.

The API and tests are a library milestone. Independent workload qualification,
x86-64, multi-MiB cases, peak-memory measurements and closing the native
throughput gap remain required before claiming a competitive release. The Lean
model has not changed; no formal Rust refinement proof is claimed.
