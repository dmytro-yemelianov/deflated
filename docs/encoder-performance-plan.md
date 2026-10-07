# Next goal: encoder performance and compression improvements

Status: active. P0 corpus/control contract and P1 profiling are implemented;
P2 isolated speed pilots are complete, P3 is underway, and P4–P6 are pending.
Evidence: [refreshed encoder profiles](encoder-profile-report.md).
Initial implementation evidence: [isolated speed spikes](encoder-speed-spikes.md).
Bounded parser prototype: [P3 investigation](encoder-bounded-parser.md).
Baseline: `14f15e63e1a8955c5cfebf869ce065f29dd950fc` (completed S0–S9).

## Objective

Investigate and implement improvements to the actual Rust encoder, keeping
separate speed, size and compromise candidates. The main compromise target
is at least 1.5× Balanced throughput with at most 1% aggregate packed-size
growth and at most 20% growth on any measured file. Seek an improved
speed/size frontier against both existing profiles and direct native
references. These are measurement targets, not promised outcomes.

Complete the investigations, verification and integration of qualifying
changes. Record rejected approaches and unmet targets with reproducible
evidence. A completed investigation must not be described as meeting a
performance target when it does not. No universal superiority claim follows
from a finite corpus or one machine.

## Starting evidence

- [Final S9 validation](final-tuning-report.md): speed 2.559× Balanced for
  +3.287% bytes, but +95% on the worst file; compromise 1.576× for +0.901%,
  but +45.6% worst-file growth; adaptive speed 1.356× for +0.635%, but +20.7%
  worst-file growth. These are valid research candidates, not promoted defaults.
- The size policy is 1.311× faster than Best and produces 0.557% fewer bytes
  on the previous mixed final set. Include this existing policy as a control;
  rediscovering its gain is not a new improvement.
- Our compromise candidate is 1.204× faster than miniz6 for +1.248% bytes on
  that mixed set. The size policy is dominated by miniz6 there. Comparisons
  depend on workload and must be repeated directly on the new corpus.
- [Encoded-cost parsing](encoded-cost-report.md) achieved -1.540% bytes but
  only 0.047× Balanced throughput. Full per-position fixed-cost DP is too
  expensive, and its costs do not optimize dynamic Huffman output.
- [Mixed blocks](mixed-block-report.md) saved only 0.028% for the existing
  Balanced 16384-token partition, with a slowdown. Avoid the prototype's
  eager full-token collection and redundant table construction.
- [GPU/search accounting](bayesian-search-report.md): proposal work consumed
  at most 0.145% of verified search time. GPU scoring was slower at 880
  candidates. Accelerating proposal selection is currently a low priority.
- [Existing profiling](perf-report.md) includes encoder sampling. Refresh
  its workload coverage and attribution; word comparisons, threshold search,
  bulk/periodic insertion and compact/four-byte chains are already implemented.

## P0 — Freeze the new measurement contract

- [x] Preserve baseline source/build hashes and binaries; measure the original
  Balanced, Fast, Best and frozen S9 candidates, including both policies.
  Compare baseline and candidate builds with the same compiler and flags.
- [x] Prepare a versioned real-workload manifest: aim for at least 24 independent
  source groups, eight each for train/validation/final test. Cover text/source,
  structured records, markup, executable/object data, already compressed data
  and mixed binary content. Each split should cover at least four classes.
  Record source, license, extraction ranges and hashes; group related versions,
  deduplicate copies, and document any coverage shortfall before final testing.
- [x] Treat all previously measured corpora, including S9, as regression data.
  Fresh source lineage and disjoint synthetic regimes define the new holdout.
  Keep final-test encoding and feature-based selection inaccessible until freeze.
- [x] Report real-only throughput/size as the primary headline, with synthetic,
  mixed, family and per-file results separately. Use the same preregistered
  order, roles and weights throughout; do not choose a favorable scope afterward.
- [x] Extend existing generators only where needed: competing distance/length
  costs, collisions under the actual hash, moving change points, short random
  islands, sampling traps, ring wraps and paired input transformations.
  Tiny/boundary cases are shared stress tests, not independent holdout evidence.
- [x] Pin direct raw-DEFLATE miniz_oxide 0.8.9 levels 1/6/9 as initial controls.
  Additional encoder references require matched framing, parameters and a
  separate preregistered comparison; historical numbers are not substitutes.

Native measurements are serial, with heavy CPU/GPU jobs paused. Include all
encoder allocations, features, policy decisions, fallback passes and emission.
Exclude input I/O and oracle checks. Use at least ten paired final sessions,
rotating files, methods and candidate/baseline order, with warm batches of at
least 20 ms (2 ms tiny). First-call observations use separate fresh processes
with resident input and exclude startup; do not label them cold OS/cache tests.
Publish summed per-file median time ratios and separate paired session means
and confidence bounds. Confidence from repeated sessions concerns measurement
noise; it does not establish population generalization.

## P1 — Refresh encoder profiles and choose implementation work

- [x] Reuse/extend the existing sampling tooling for original Balanced, Best,
  miniz and the strongest S9 compromise on 8–12 representative regression or
  training inputs, including the outliers. Keep instrumented/profile runs
  separate from benchmark timings.
- [x] Attribute inclusive/exclusive samples, including inlined code; report
  unresolved samples and overlap rather than summing inclusive percentages.
- [ ] Add optional research counters where sampling is insufficient: candidate
  visits, comparison lengths, insertions, short-match rejection, tokens/blocks,
  Huffman rebuilds, allocation counts/bytes and fallback frequency.
- [x] Rank the measured costs and select at most three implementation spikes.
  Candidate areas are index traversal/cache footprint, avoidable initialization
  or allocation, repeated frequency/code construction and emission overhead.
  A hypothesis is not a measured hotspot until the profile supports it.

Delivered: `docs/encoder-profile-report.md`, 44 complete profiles, additive and
inclusive attribution counters, and 605 paired native control rows. Sampling
supports three initial spikes; additional matcher counters are deferred until
ambiguity requires them. Selected spikes: bounded code reversal, candidate/
position bookkeeping, and equivalent accepted-match range checks.

## P2 — Speed improvements with unchanged search semantics where possible

- [x] Implement the selected P1 spikes in isolation; prefer reducing work over
  changing coverage. Keep experimental branching and instrumentation out of
  the default hot path.
- [x] For equivalence-preserving changes, compare against the scalar/current
  implementation's token stream and output on meaningful collision, tail,
  periodic and wraparound cases. Do not duplicate already completed optimizations.
- [x] For changed search coverage, validate each accepted match, complete token
  expansion and deterministic emission; measure size rather than assuming it.
- [x] Measure native end-to-end cost, tiny latency and separate process RSS.
  Try portable changes first; isolate target-specific variants and compiler flags.
- [x] Combine only independently useful changes, then remeasure interactions.

Delivered: [P2 evidence](encoder-speed-spikes.md), 3900 serial paired rows,
162 separate RSS processes, and scalar/legacy equivalence gates. Code reversal
is retained (1.042× Balanced on real validation); iterator, range-check and
position rewrites are rejected. No changed-coverage implementation or
multi-change combination was admitted. First-call and integrated binary-size
guards remain P5 work; final-test inputs are still reserved.

Initial budget: at most three bounded implementation spikes and 32 canonical
variant evaluations. Extend only when a documented result justifies the next
experiment. Keep negative results and reproducing inputs.

## P3 — A cheap parser aware of encoded cost

- [ ] Reuse the S7 exact fixed-code oracle and counterexamples as diagnostics.
  Start with bounded alternatives and short lookahead, not full-input DP.
- [ ] Compare longest/one-step lazy against candidate budgets 4/8/16 and a
  small set of lookahead or beam widths. Prune redundant alternatives and cap
  work explicitly. Preserve accepted-token checks and the 32768 distance bound.
- [ ] Evaluate costs using estimated/current literal, length and distance
  Huffman lengths plus extra bits. Record estimation error; reconstructed
  dynamic tables and header costs determine the actual output size.
- [ ] Permit at most one additional bounded cost/refinement pass initially.
  Measure every pass. Do not claim global optimality from a bounded graph or
  estimated code lengths.
- [ ] Compare size candidates to both Best and the old size policy, with matched
  timings and memory. Reject savings whose runtime exceeds the size-role budget.

Initial budget: at most 24 canonical variants; select finalists on training,
confirm on validation. Retain exact witnesses and measured cost breakdowns.

## P4 — Adaptive compromise and block decisions

- [ ] Diagnose the S9 fast/compromise outliers with existing regression data.
  Extend the current cheap policy using source-grouped validation and new
  features only when their native overhead is justified.
- [ ] Vary search effort by region: fast effort on easy regions, a bounded
  larger budget on ambiguous regions. Include sampling traps and regime drift.
- [ ] Compare feature-only selection, restricted local retries and a fully
  charged exact baseline-comparison fallback. The latter can enforce a
  per-input baseline-size threshold but requires extra encoding work; a
  predictor alone cannot guarantee it for unseen inputs. Distinguish measured
  holdout limits from any claimed universal bound.
- [ ] Spike streaming fixed/dynamic/stored selection at detected regime changes,
  reusing frequencies and avoiding eager whole-input tokens/evidence allocation.
  Compare identical partitions first, then adaptive boundaries; charge headers,
  byte alignment, stored length limits and any retained buffers.
- [ ] Preserve history across blocks and exactly one final block. Review Lean
  emitter scope before production integration of mixed stored blocks.
- [ ] Retain separate maximum-speed, minimum-size and compromise profiles.
  Looser opt-in tradeoffs need explicit reporting and must not silently relax
  the main compromise guards after seeing results.

Initial budget: at most 24 adaptive-policy/block variants. Evaluate standalone
and selected P2/P3 combinations; control total search rather than exhaustive
cross-products. Cheap, interpretable CPU selection remains the baseline.

## GPU and Lean checkpoints

GPU: perform a fresh whole-loop accounting check after P1–P4 change the workload.
Reopen a small scoring spike only if proposal/model work becomes at least 5%
of wall time or a validated larger batch demonstrates an end-to-end benefit.
Include fitting, synchronization, transfer and native verification. A full
GPU encoder is a separate architecture spike, requiring a new measured
bottleneck and a local bounded feasibility case. No cloud spending is part
of this goal; record a reasoned defer decision if the trigger is absent.

Lean: existing checked finder/token and fixed/dynamic/split model theorems
permit heuristic experiments; they do not prove Rust or performance. Structural
emitter changes require an append/alignment model, cross-block decoder invariant
and applicable roundtrip proofs before production promotion. Keep the pinned
toolchain and standard-axiom gate. Follow [verification-boundary.md](verification-boundary.md);
finite native/Lean packet agreement remains test evidence, not refinement.

## P5 — Freeze finalists and validate independently

- [ ] Freeze role candidates, source/binary/policy hashes, guards and corpus
  manifest before any final-test encoding. Never retune on that final test;
  another revision needs a new holdout or an explicitly non-blind regression.
- [ ] Run the paired warm/first-call protocol and direct native references.
  Validate every accepted output with deflate-core, miniz and exact-consumption
  zlib. Preserve failures, timeouts and aborted runs in the ledger.
- [ ] Measure RSS in separate processes on representative large real/synthetic
  inputs (three repetitions), and tiny-input latency per case. Measure actual
  integrated binary sizes separately from research workers and policy payloads.
- [ ] Check new emitted packets through the actual Lean and Rust CLI decoders;
  add targeted correspondence/model tests where token/emitter contracts change.
- [ ] Publish all roles, family/file regressions and native-reference tradeoffs,
  including candidates that miss a target. Do not hide negative results in an
  aggregate or substitute an easier comparator.

Predeclared targets/guards on the new primary real scope:

| Role | Warm and first-call speed target | Aggregate packed-size guard | Per-file size guard |
| --- | --- | --- | --- |
| Speed | paired session lower 95% bound ≥1.5× original Balanced | ≤1.20× original Balanced | ≤1.20× original Balanced |
| Compromise (main target) | paired session lower 95% bound ≥1.5× original Balanced | ≤1.01× original Balanced | ≤1.20× original Balanced |
| Size | paired session lower 95% bound ≥0.5× original Best | ≤0.998× original Best | ≤1.20× original Best |

Also apply aggregate size and per-file size limits to synthetic/regression
scopes and report their speed separately. To call a result a *new* improvement,
it must improve the frontier among profiles satisfying the same role guards,
including the old size policy, on the frozen new workload. Fixing a worst-file
failure can qualify even when an old guard-violating profile has better aggregate
speed/size. A size guard alone is not evidence of superiority over miniz.

For every role: decoder-time upper 95% ratio ≤1.20× its role baseline; worst
tiny warm-median latency ratio ≤1.20×; maximum per-case median peak-RSS increase
≤8 MiB; portable release binary growth ≤64 KiB. Speed/compromise use original
Balanced as the role baseline; size uses original Best. These guards apply
to the measured cases and builds. Report missing evidence as missing.

## P6 — Integrate qualifying changes and finish

- [ ] Integrate useful candidates through appropriate existing APIs or explicit
  opt-in profiles. Change defaults only when their preregistered guards pass.
  Keep rejected prototypes isolated and documented; preserve raw-stream/framing
  contracts and the default build without research dependencies.
- [ ] Run formatting/Clippy, applicable default/all-feature Rust tests, research
  checks, Lean/model/axiom gates, differential/framing suites and the existing
  bounded fuzz targets. Add tests for changed contracts or counterexamples,
  not mirror tests for every implementation detail.
- [ ] Recheck the integrated build when its hot path differs from the measured
  finalist. Require relevant CI on the final exact revision before release
  claims, and retain source/build/corpus provenance with raw compressed ledgers.
- [ ] Publish `docs/encoder-improvement-report.md`: achieved targets, direct
  references, remaining gaps, profile-guided explanations and next hypotheses.
  Update this checklist and link accepted/rejected artifacts; commit the scoped
  work without touching the unrelated preexisting `memory/` directory.

Completion requires P0–P6 and the GPU/Lean decisions to be resolved with
evidence. Successful performance promotion is conditional on the frozen
guards; investigated negative results may complete the research objective
but never count as achieved speed/size targets.
