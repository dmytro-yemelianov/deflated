# G0 resident-input workers

This is a tooling/correctness checkpoint on Apple M5/macOS, not a performance
study. No study train/validation/holdout encoding has occurred. The complete
`new-methods-reference-lock.json` is now frozen before screening. The active
[plan](new-methods-plan.md) and [protocol](../scripts/new_methods_protocol.json)
retain their configuration, selection and final-session budgets.

## Implemented controls

The [C adapter](../scripts/native_codec_worker.c) builds one executable per
codec, linked only to its own isolated library family. The seven pinned
libraries and their compile commands are recorded in
`scripts/reports/new-methods-reference-sources.json`. Ordinary encode/decode
calls pay state creation/destruction, output allocation, framing, CRC/checksum
and finalization. Input loading and output writing are outside codec timers.

| Codec | Levels | Complete framing / settings |
|---|---|---|
| zlib 1.3.2 | 1, 6, 9 | raw DEFLATE; window 15, memory 8, default strategy |
| zlib-ng 2.3.3 | 1, 6, 9 | native API; same DEFLATE parameters |
| libdeflate 1.26 | 1, 6, 9, 12 | raw DEFLATE |
| zstd 1.5.7 | −1, 1, 3, 9 | content size + checksum; zero worker threads |
| LZ4 1.10.0 | default, HC9 | 64 KiB blocks; block and content checksums; content size when nonempty |
| Brotli 1.2.0 | 1, 5, 9 | generic mode, window 22; BRF1 magic + u64 size + u32 CRC32 before native stream |
| LZMA2 / xz 5.8.4 | presets 1, 6 | XZ frame with CRC32; no BCJ filter |

Every codec uses one thread and no external dictionary. Native LZ4's one-shot
API emits an independent single block for inputs ≤64 KiB, including empty
input; larger frames use linked blocks. Its reusable encoder explicitly uses
the corresponding mode and reproduces fresh packets.

The [Rust tools crate](../tools/new-methods-bench/Cargo.toml) is unpublished and
separate from both runtime crates. Three independent executables expose:

| Worker | Methods |
|---|---|
| `core_worker` | b7-compatible Fast, Balanced, Best; exact core source hash gate |
| `miniz_worker` | pinned miniz_oxide 0.8.9 levels 1, 6, 9 |
| `structured_worker` | all 12 DSC1 settings and two same-framing untransformed controls |

All DEFLATE workers additionally implement matched gzip and one-entry ZIP:
gzip has zero timestamp, OS 255 and no optional fields; ZIP uses `data.bin`,
DOS 1980-01-01, method 8, no extra/comment/descriptor. Overheads are 18 and
114 bytes respectively. Rust and C construct the same metadata. Each timed
container encode computes its CRC and allocates/copies the complete frame.

Rust core/miniz decoder drivers add exact member consumption and expected
output-length checks inside the measured call. The core's public decoder keeps
its existing suffix semantics. Both miniz's fresh decoder state and its
geometric output-buffer growth remain charged. No raw decoder throughput is
silently substituted for framed decoding.

## Timing and context

All workers share this argument shape:

```text
WORKER MODE CODEC LEVEL FRAMING INPUT OUTPUT MIN_NS EXPECTED_RAW [SECOND_INPUT]
```

`encode` / `decode` validate packets. `memory-encode` / `memory-decode` isolate
RSS directions. `cold` retains the first packet and reports the first encode
and decode calls, with no priming encode. `warm` also runs independent batches
until each direction reaches `MIN_NS`, freeing each batch result inside the
timer. Inputs are resident; encoded packets are not supplied to encoders as
cached results. DSC1 pays its full transform, reconstruction check, dictionary,
four substream encodes, original DEFLATE alternative, selection and CRC.

`reuse-cold` / `reuse-warm` are separately labelled. zlib/zlib-ng, libdeflate,
zstd and LZ4 reuse allocated contexts, charge reset/configuration on each call
and report initialization separately. A→B→A checks require byte-identical
packets to fresh contexts and exact decoded bytes. Brotli/LZMA2 report
`fresh-no-reset-api`, with initialization zero because it is already charged
inside every call. Rust tools report `fresh-no-reuse-adapter`: the selected
one-shot APIs recreate their working state, including miniz. This label is
about the adapter, not a claim that the library cannot expose other APIs.

The C workers use `mach_absolute_time` on this host because `CLOCK_MONOTONIC`
quantized to microseconds. Rust uses `Instant`. All observed minimum clock
steps are 41 ns. Timer overhead is neither subtracted nor presented as a speed
gain. Contract-test batches are diagnostics, not training or holdout samples.

## Finite evidence

Compressed receipts in `scripts/reports/` retain every packet/raw hash:

- Native: 328 independent decoding cases, 1,888 malformed/size/checksum
  rejections, 328 fresh/reused A→B→A checks, 82 reusable timing contracts.
- Rust: 448 independent decoding cases, 2,604 malformed/size/checksum
  rejections, 448 stateless A→B→A checks, 256 cold/warm/context timer contracts.
  All 84 raw Fast/Balanced/Best/miniz fixture packets match the archived b7
  research worker.
- The actual default CLI remains byte-identical to sealed b7, 542,304 bytes.
  The unchanged experimental `structured-tool` is 538,688 bytes. These are
  host/release-profile build facts, not throughput or promotion results.

The shared witnesses include empty/tiny inputs, raw byte-domain data, invalid
UTF-8, duplicate keys, escape/numeric spellings, u64 boundaries, random history
and both 64/256 KiB chunk boundaries. They do not represent independent data
populations or complete formal refinement. DSC1's existing normative oracle,
fuzz and CI scope remains described in the specification.

OpenZL v0.3.0's library built on the first dependency setup attempt, using the
upstream default introspection setting. The second and final allowed setup
attempt disabled introspection and enabled the upstream CLI as an independent
oracle. That shared-library/CLI build failed while linking
`cli/utils/libutils.dylib` on ARM64, with unresolved `ArgParser` symbols. Both
attempts and the second configure/build logs are preserved in
`new-methods-openzl-feasibility.json` and its compressed log companion.
OpenZL is therefore excluded from the bounded measured roster: no qualification,
performance result or superiority over OpenZL is claimed. Typed numeric or
trained graphs are not substitutes for byte-exact JSON reconstruction.

## Immutable reference lock

The decoder-only supplement is frozen separately in
`scripts/reports/new-methods-decoder-lock.json`. The original workers' cold
`first_decode_ns` follows an encoder call in the same process; that field is
paired first-decode timing, not fully cold decoder initialization. Study
first-decode measurements therefore use the supplement's separate process,
which reads a resident packet and calls no encoder before the timer. Its C
entrypoint includes the unchanged v1 decoder/framing routines; the Rust
entrypoints include the unchanged v1 adapters. Warm loops create fresh decoder
state and pay output allocation/destruction, CRC and exact consumption.
This changes executable layout, explicitly recorded in the supplement, without
rebuilding or replacing the v1 control binaries or their reference lock.

All 73 codec/level/frame settings pass cold/warm checks on two shared witnesses:
292 timer/output contracts and 584 truncation/suffix/concatenation/size rejects.
The Rust timer's unit witness panics if an encoder is invoked. Static call-path
inspection supports the corresponding C no-encoder boundary; this is finite
evidence rather than machine-code refinement. The sixth common C compiler check
and second contract-fix round were used, before study screening; original G0
receipts remain unchanged. Audit with
`python3 scripts/new_methods_decoder_lock.py --check --local`.

`scripts/reports/new-methods-reference-lock.json` binds all nine reference
implementations to source/archive hashes, release/compiler/build settings,
APIs, codec levels, single-thread and dictionary rules, worker/library hashes,
framing and the exact independent validation receipts. It also records the
initial DSC1 binary separately as an unqualified prototype.

```sh
python3 scripts/new_methods_reference_lock.py --check
python3 scripts/new_methods_reference_lock.py --check --local
```

The first command audits published receipts without requiring installed native
libraries; the second rechecks actual local libraries, workers and archived b7
binaries. The miniz source used by Cargo was compared file-for-file with its
pinned crate archive before locking. Local worker directories carry `.frozen`
markers and their builders refuse replacement. The study controller must audit
this lock before timing. Corpus acquisition/deduplication may proceed before
finalist freeze; held encoding or feature extraction may not.

## Reproduction

```sh
python3 scripts/new_methods_references.py --out target/reproduce/references \
  --codec zlib --codec zlib-ng --codec libdeflate --codec zstd \
  --codec lz4 --codec brotli --codec lzma2 \
  --source-lock scripts/reports/new-methods-reference-sources.json
python3 scripts/new_methods_native_build.py --references target/reproduce/references \
  --out target/reproduce/native --check-note 'fresh reproduction of frozen source'
python3 scripts/test_native_codec_workers.py --workers target/reproduce/native
python3 scripts/new_methods_rust_build.py --out target/reproduce/rust
python3 scripts/test_rust_codec_workers.py --workers target/reproduce/rust \
  --baseline target/new-methods/baseline-b7/research_worker
```

The native reproduction currently requires macOS `clang`, CMake, Ninja and
`otool`, plus independent zstd/LZ4/Brotli CLI decoders. Rust worker contracts
also run in Linux CI. Build seals refuse successful-output replacement;
the native compiler-check ledger persists before compilation and enforces
six checks/two contract-fix rounds. A frozen worker directory prohibits rebuild.
Use a new output path for reproduction, preserving failed attempts.
