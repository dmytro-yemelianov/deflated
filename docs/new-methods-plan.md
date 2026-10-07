# New compression methods: bounded investigation plan

Status: closed by maintainer decision on 2026-10-07; project in maintenance
mode. G0/G1 and the independent DSC1 prototype are complete. All 12 B settings
failed the charged training screen; no sentinel was selected. A was cancelled
before implementation. Remaining proof, validation, held/RSS and promotion
work was cancelled, not passed. See the [closure report](new-methods-report.md)
and [handover](handover.md) for final dispositions and retained evidence.
The protocol and checklist below record the original scope; unchecked items
are historical unfinished work, not an active backlog. No new performance or
research-novelty claim follows from this campaign. Baseline:
`b7d5e0fc79f4f72d2ba772312ec9a22497699ed5`.

## Objective and deliverables

Investigate two concrete prototypes:

1. [A: tagged/grouped DEFLATE matcher](matcher-prototype-spec.md), retaining
   ZIP/gzip/DEFLATE interoperability and the checked-token contract.
2. [B: byte-exact structured codec](structured-codec-spec.md), an experimental
   self-contained format for JSON/NDJSON/log-like bytes with its own decoder.

Deliver reproducible sources, pinned native controls, acquisition/generator
manifests, independent test evidence, model proofs in their stated boundary,
all accepted/rejected measurements and a final `new-methods-report.md`.
The original objective was to resolve all stages; it was not fully achieved.
The maintainer's closure supersedes that objective without claiming the
numerical targets. General-purpose entropy formats, long-distance codecs and
full GPU encoding were outside this budget and are not scheduled follow-ups.

The [machine-readable protocol](../scripts/new_methods_protocol.json) fixes
targets and budgets. G0 must fill a separate immutable reference lock with
exact release commits, compiler flags, APIs, levels, binaries and data hashes
before native screening. Missing locks prohibit measurement and claims about
that reference; they do not justify substituting old numbers.

## G0 — Sources, prior work and controls

- [x] Preserve the baseline archive, default/research workers and actual CLI;
  verify core/source/compiler/policy hashes and old byte identities.
- [x] Record [related work](new-methods-related-work.md). Read the relevant
  implementations before designing a purported new mechanism; identify the
  particular contribution rather than claiming that dictionaries, fingerprints,
  delta encoding or stream separation were invented here.
- [x] Build local single-thread native adapters for current baseline presets,
  miniz_oxide 0.8.9, zlib, zlib-ng, libdeflate, zstd, LZ4/LZ4-HC, Brotli and
  liblzma LZMA2. Lock exact releases/builds before screening. OpenZL is an
  additional structured reference when its bounded setup succeeds; record
  absence explicitly. At most two documented setup/build attempts per adapter
  dependency before narrowing claims to the available verified controls.
- [x] Validate adapters against independent decoders, empty/tiny data and
  incorrect/truncated framing. Use resident-input library calls, not CLI
  subprocess startup as encoder time. Charge creation/destruction of codec
  state and output allocation in the ordinary end-to-end track.

DEFLATE comparisons use raw streams first, then matched gzip/ZIP containers
as an end-to-end secondary track. Cross-format comparisons include complete
self-contained frames, checksums and metadata, with ordinary single-thread
settings. Also publish reusable-context throughput separately, including its
initialization and reset rules; it cannot replace the end-to-end headline.
Use all preregistered levels, not a favorable level selected on final data.

## G1 — Fresh data and synthetic stress

- [x] Acquire versioned corpora with eight train/validation/test source groups
  per track (up to 48 groups total; a source may occur in both tracks only in
  the same split). A includes six general-content classes; B includes JSON,
  NDJSON and line records, with at least two classes per split. Aim for eight
  independent held groups in each primary scope; document shortfalls before
  any test encoding, and prohibit an independent headline with fewer than six.
- [x] Exclude every previously measured source lineage from new holdout
  eligibility. Group project versions, mirrors, schema/template relatives and
  paired transforms together across both tracks. Preserve URLs, pinned versions,
  licenses, extraction ranges, hashes and copy/near-copy checks.
- [x] Use complete files up to 1 MiB or recorded bounded slices. Preregister
  a small separate 8 MiB long-history/chunk-boundary stress track; do not
  silently aggregate it into the primary score.
- [x] Keep acquisition limited to downloading, signature/hash validation and
  deduplication. No held encoding, feature extraction, teacher labels, fitted
  schema or dictionary construction before G5 freeze.
- [x] Extend deterministic generators using disjoint regimes 13/14 train,
  15/16 validation and 17/18 held. Add actual-hash/tag collisions, 3-byte matches
  with unequal fourth bytes, cache eviction, ring generations, lazy pending
  candidates, numeric spellings/overflow, escaped quotes, raw invalid UTF-8,
  schema drift, unique keys and chunk-spanning lexemes. Keep tiny/boundary
  witnesses shared stress, and all prior corpora labelled regression.

The [data checkpoint](new-methods-data.md) records 36 source groups, eight per
track/split, 72 synthetic cases, six separate 8 MiB long cases and 21 shared
tiny/boundary witnesses. The eighteen historical manifests retain 1,252 case
records / 399 unique hashes; all fifty unique old real inputs pass comparison
against the fresh real files. Byte deduplication is not a semantic independence
proof. B training and shared stress were subsequently encoded in the completed
screen; validation/held codec screening and fitting did not occur before closure.

## G2 — Matcher screen

- [ ] Implement scalar reference and counters outside the timed specialization.
  First screen the 12 equivalence-preserving configurations in specification A.
  Require candidate/probe/state, complete token and packet equivalence before
  measurement. Include bulk/periodic insertion and pending-literal lookahead.
- [ ] Screen the eight contiguous-bucket configurations separately. Coverage
  changes require full accepted-token validation and actual size measurement;
  no equality claim or predictor-based universal size cap.
- [ ] One fully charged training session selects at most two A sentinels:
  best equivalence speed and best guard-feasible speed/size. Confirm each in
  three validation sessions. Keep all negative variants; reject a family early
  when no training point warrants confirmation.

Initial budget: 20 canonical A configurations. No extra grid, combination or
architecture-specific branch without a written measured reason and explicit
budget amendment before further evaluation. Prior iterator, accepted-range,
regional-budget and stored-predictor negatives remain controls/diagnostics.

## G3 — Structured format and independent reference

- [x] Implement the standalone specification B reference decoder and normative
  vectors before Rust encoding. Complete byte layout, canonical varints,
  exact consumption, output/work budgets and deterministic error categories.
- [x] Implement an isolated `structured-codec` crate with `no_std + alloc`,
  `forbid(unsafe_code)` and only the local `deflate-core` dependency. Keep
  reference libraries in benchmark/oracle tooling. Default DEFLATE APIs and
  wire format retain their contract; B is explicitly experimental.
- [x] Screen 12 B configurations: chunk log2 16/18 × dictionary mode off/keys/
  all-quoted × numeric mode off/checked-delta. Always charge scanning, dictionary
  selection, all four substream encoders, byte reconstruction checking, CRC,
  exact raw/DEFLATE alternatives and final size selection. No free retry.
- [x] Resolve B selection on training: all 12 failed the point guards and no
  sentinel was selected. Three-session validation was not warranted or run.
  Rebuilt whole-frame costs decide usefulness. An unsuccessful transform can
  finish as a documented negative; the format roundtrip does not imply a win.

Initial budget: 12 canonical B configurations. Cross-product tuning across A
and B is excluded; B uses the sealed baseline DEFLATE backend initially.
Only an independently useful A result may justify one later preregistered
combination before G5. No learned dictionary, external schema, custom entropy
coder or domain filter is smuggled into this initial roster.

## G4 — Correctness and model boundary

- [ ] For A, retain every `accept` check and current emission. Add meaningful
  scalar-state/token/packet counterexamples and native/Lean/zlib packet agreement.
  Existing finder/split theorems remain model statements, not Rust refinement.
- [ ] For B, prove the transform reconstruction and state invariants in a new
  Lean namespace: literal/dictionary expansion, canonical integer rendering,
  checked delta/zigzag inversion, progress and output bounds. Model arbitrary
  checked transform proposals independently of the heuristic scanner.
- [ ] Review and model strict standalone compressed-member consumption. Current
  `inflate_with_limit` permits a suffix; a strict B helper must track consumed
  bytes without silently tightening the existing public decoder. Re-run decoder
  correspondence and default performance/size if shared hot code changes.
- [ ] Require frame composition/roundtrip model proofs before promotion of B.
  Keep standard-axiom gates and Lean 4.30.0. An uneconomic prototype can be
  rejected before full frame proof; report the unproved scope and retain it in
  research only, rather than declaring verification complete for production.
- [ ] Run deterministic cross-language vectors, mutations, truncations and
  bounded fuzz for B frame/operations/roundtrip plus existing DEFLATE targets.
  Require exact original bytes, including whitespace, duplicate keys, escape
  spelling, negative zero, leading zeros and noncanonical numerals.

## G5 — Freeze and independent confirmation

- [ ] Freeze at most three finalists (two A, one B), sources, binaries, all
  codec settings, reference lock, corpora and contract before opening held data.
  Reject a restarted/edited study directory; preserve failures and partial rows.
- [ ] Run ten serial paired sessions, minimum 20 ms warm/2 ms tiny, fresh-process
  first-call timers, complete-session bootstrap (10,000 resamples), actual decode
  timing, per-file/family results and all direct native controls.
- [ ] Measure separate encode and decode whole-process RSS, three replicates
  on largest cases per class plus collisions/drift. Measure actual default CLI
  and standalone B tool size, and tiny encode/decode latency per input.
- [ ] Validate every timed packet independently. A: core/miniz/zlib plus Lean
  finalist packets. B: independent reference and Rust plus executable model
  vectors/packets in the explicitly proved frame scope. Never retune on held
  results; future candidates need a new holdout or regression-only label.

Targets are fixed before observations. A-equivalent: ≥1.10× current Balanced
warm lower 95% bound, first-call lower bound ≥1.00×, unchanged packets and
common guards. A-coverage: ≥1.50× current Balanced warm/first-call lower bounds,
≤1% aggregate and ≤20% each-file byte growth across all non-tiny scopes.
B-size: ≥5% fewer whole-frame bytes than zstd level 3 on the structured primary
scope, ≥0.25× its encode throughput lower bounds and ≤3× its decode time upper
bounds; ≤10% growth on any primary/regression structured file. Also require
≥2% savings over B's own same-framing untransformed DEFLATE control. B-compromise
is a separately reported stretch target of ≥1.10× zstd3 speed with ≤1% bytes.
Targets are experiments, not forecasts. Broad statements about other levels,
formats, source populations or platforms need corresponding direct evidence.

Common A guards use b7 Balanced: each-file decode time upper 95% bound ≤1.10×,
each tiny encode/decode upper bound ≤1.20×, separate encode/decode whole-process
RSS growth ≤8 MiB and actual default CLI growth ≤64 KiB. B uses checksummed
zstd3 frames: each tiny encode/decode upper bound ≤2×, encode RSS growth ≤32 MiB,
decode RSS growth ≤16 MiB and standalone tool growth ≤256 KiB relative to the
sealed b7 CLI under the same release profile. These are experimental resource
budgets, not inferred guarantees. Tiny inputs are evaluated separately from
aggregate packed ratios; unavoidable framing overhead still appears in their
published sizes. Report all preregistered scopes even when a primary target passes.

## G6 — Integration and completion

- [x] Resolve promotion: no new path or format qualified; none promoted.
  The original rule required unchanged DEFLATE contracts for qualified A paths,
  explicit coverage tradeoffs, and B's model/frame, correspondence and measured
  role gates before opt-in exposure. Those promotion gates were not reached.
- [ ] Run format, default/all-feature Clippy and applicable Rust/research/model/
  axiom/differential/framing/fuzz suites. Require successful CI at the exact
  final revision, and remeasure any integrated hot-path change.
- [x] Publish completed budgets, reference comparisons, regressions, failed novelty
  hypotheses and proof gaps in `docs/new-methods-report.md`; retain compressed
  raw ledgers and build/source/corpus receipts with reproduction tooling.
- [x] Resolve the GPU decision: B proposal/selection was 0.0148% of its loop;
  no GPU work justified. A accounting was cancelled with A. Proposal/fitting work
  needs ≥5% of the measured loop or a demonstrated larger-batch whole-loop
  benefit to reopen scoring. A GPU encoder spike needs a separately measured
  GPU-suitable bottleneck and a bounded CPU/native baseline; no cloud spending.

The original all-stage completion requirement was not met. Closure records
both B's honest early rejection and the maintainer's cancellation of A and
remaining gates; it is not a completed evaluation of every planned method.
Unrelated `memory/`, `.DS_Store` and existing study artifacts are preserved.

## Initial implementation checkpoint

- `scripts/new_methods_seal.py` archived/built b7 separately; the default CLI
  and default worker reproduce their previous binary hashes. The research
  worker has a separately recorded build hash; 30 Fast/Balanced/Best/miniz
  packets agree with the previous worker and independent zlib.
- `scripts/structured_reference.py`, `tests/structured/vectors.json` and
  `scripts/structured_correspondence.py` check normative success/error precedence
  and all 12 configurations on 14 shared correctness witnesses. These witnesses
  are not independent performance holdout. Published receipts state the finite
  scope; they establish neither a Lean proof nor a compression/speed result.
- `scripts/new_methods_references.py` builds seven pinned releases into isolated
  directories. The published source/build receipt is deliberately distinct from
  the required full reference measurement lock: native adapters, settings and
  independent framing tests are still required before screening.
- Research B is unpublished/experimental. The ordinary core implementation and
  existing decoder suffix contract retain their current behavior. DSC1 has a
  separate strict block driver using existing checked decoding primitives.

Reproduce the correctness checkpoint:

```sh
python3 scripts/test_structured_reference.py
cargo test -p structured-codec --all-features
cargo build --locked --release -p structured-codec --features cli
python3 scripts/structured_correspondence.py
python3 scripts/new_methods_seal.py --out target/new-methods/b7-reproduction
python3 scripts/new_methods_references.py --out target/new-methods/reference-reproduction \
  --source-lock scripts/reports/new-methods-reference-sources.json
```

The last two commands refuse successful-output replacement; use a fresh path.
The subsequent [worker checkpoint](new-methods-benchmarking.md) documents the
mandatory resident-input adapters, matched framing, charged state and independent
contract checks. G0 is now resolved by the immutable
`scripts/reports/new-methods-reference-lock.json`; OpenZL's bounded exclusion is
part of that lock. G1 is resolved by the published data/audit/regression receipts.
B's subsequent charged training screen is published in the closure report.
G2 and remaining G4–G5 work were cancelled. No further checkpoint is scheduled.

## G0 budget clarification, before study screening (2026-10-07)

The two-attempt dependency setup cap remains: each of the seven native source
libraries built on its first attempt. Adapter development now has an explicit
maximum of six compiler checks and two contract-fix rounds for the common C
worker, separate from dependency feasibility. This clarification is recorded
before any train/validation/held codec measurement; it does not expand A/B's
configuration, selection or final-session budgets.

At this historical checkpoint five common C compiler checks had been used:
fresh-state worker; correction
of native LZ4's independent one-block header and macOS clock resolution;
implementation of the planned reusable-context track; reset-check argument
guard; zero initialization accounting for unsupported one-shot reset APIs and
build-budget enforcement. One contract-fix round was used. Clock/format
diagnostics use shared correctness witnesses only. Resets on A→B→A inputs and
reusable timer contracts now pass. Brotli/LZMA2 remain fresh state with zero
separate initialization reported. Later implementation recompilation after
dependency feasibility is established is not a new dependency setup spike;
preserve its own bounded build/fix ledger.

The decoder-only supplement later consumed the sixth compiler check and second
contract-fix round; its separate lock and ledger preserve that final budget
accounting. These were completed before B screening. No additional native
adapter development is planned after closure.
