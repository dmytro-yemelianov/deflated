# S2/S3: mixed workloads, CPU optimizers and measured memory

This frozen campaign compares 3 CPU search strategies across 3 seeds,
then checks training-selected finalists on full real files and larger synthetic
cases. Production presets are unchanged. The real holdout was previously
visible, so these are regression results rather than fresh final-test evidence.

On real validation, the training speed representative reaches 2.32× Balanced throughput
with +17.01% output size. The size representative changes output by
-0.33% at 0.41× throughput. The training compromise
reaches 1.62× with +3.32% output size.

## Frozen experiment

[The protocol](../scripts/search_protocol.json) fixes 32 unique configured
evaluations per strategy/seed, 5 rounds of at least 5 ms and a separate
128-configuration factorial. Strategy order rotates across seeds. Finalists are
frozen before 7 validation rounds of at least 10 ms and direct reference checks.

Training uses 20 synthetic 256 KiB regimes and 13 real source-file chunks,
7.57 MB total. Validation has 13 larger synthetic cases and 13 full real files,
154.67 MB total. Original source-file train/holdout assignments are preserved.
Fourteen full synthetic test cases remain reserved and were never encoded.

The CPU strategies are random, the earlier Pareto-mutation heuristic and
[Optuna 4.5.0 NSGA-II](https://optuna.readthedocs.io/en/v4.5.0/reference/samplers/generated/optuna.samplers.NSGAIISampler.html)
with population 16 and categorical axes. Duplicate proposals reuse verified
training scores; the budget counts unique encoder evaluations. Failed trials
abort and receive no invented objective. Native encode timing includes allocation
and excludes I/O/decoder checks. Both candidate and baseline streams pass
deflate-core, miniz_oxide and exact-consuming zlib checks.

The optimizer samples 880 joint configurations from the recorded
categorical axis levels. This is a discrete subset of the adapter's wider
valid integer ranges; the report retains the levels alongside the factorial.

## Optimizer comparison on training

Hypervolume minimizes normalized time and size, with fixed reference (4, 1.5)
and Balanced anchor (1, 1). Points outside that box do not contribute. Stored
and reference encoders are excluded. Values summarize this measured budget;
they do not certify optimizer superiority or global optimality.

| Strategy | Hypervolume median [min, max] | Recorded study seconds median | Timed optimizer fraction max |
| --- | ---: | ---: | ---: |
| random | 1.7966 [1.7786, 1.8078] | 118.03 | 0.002% |
| pareto-mutation | 1.8258 [1.8061, 1.8411] | 124.05 | 0.003% |
| nsga2 | 1.8008 [1.7413, 1.8168] | 125.44 | 0.101% |

Recorded study time includes the cached build, proposals, encoder evaluation,
oracle checks and in-run integrity guards. Initial process startup and
manifest/provenance preparation precede that study clock; corpus generation
and downloads are separate. The campaign wall time also includes full-file
validation, bootstrap computation, reference checks and RSS runs. Unique
evaluation budgets are matched; wall-time stop budgets are not. This study
does not establish time-to-target superiority.

## Frozen representatives on real validation

Representatives are chosen from training only. Other per-study role
finalists and prior synthetic sentinels are retained in the evidence. Speed
intervals resample real source files and paired rounds; they reflect workload
variation as well as timing noise.

| Role | Configuration | Speed vs paired Balanced [95% interval] | Size vs Balanced | Max file size change |
| --- | --- | ---: | ---: | ---: |
| speed | p1, greedy, tail4, trigram, split16384 | 2.32× [1.81, 2.92] | +17.01% | +38.40% |
| size | p1024, lazy, tail0, trigram, split16384 | 0.41× [0.34, 0.53] | -0.33% | +0.00% |
| balanced | p32, greedy, tail32, trigram, split16384 | 1.62× [1.46, 1.75] | +3.32% | +7.69% |

The predeclared compromise aggregate size guard (+1%) fails on real validation.
The per-file size guard (+20%) fails for: speed.
These guardrails report transfer failures; they do not trigger a new selection
using the validation results.

The Balanced-vs-itself real control measures 1.0002× [0.9963, 1.0105] with identical encoded sizes. This is a control for
paired measurement variation in this run, not a bound on future timing noise.

Production Best changes real output size by -0.62% at 0.57× Balanced speed.
It dominates the training size representative on these measured normalized
aggregates. This is a transfer failure, not a newly better compression
policy. The speed comparison uses separate paired-Balanced sessions;
the compressed sizes are exact. The frozen representative remains unchanged.

## Prior synthetic winners on expanded validation

These configurations were frozen from the earlier S1 pilot. The columns
below are measured in this campaign on its larger synthetic validation
cases and full real files, rather than comparisons between separate runs.

| Configuration | Synthetic speed vs Balanced | Synthetic size change | Real speed vs Balanced | Real size change |
| --- | ---: | ---: | ---: | ---: |
| p256, lazy, tail0, trigram, split16384 | 0.59× | -2.17% | 0.59× | -0.22% |
| p1, lazy, tail32, trigram, split16384 | 2.08× | +0.60% | 1.93× | +12.77% |
| p2, greedy, tail16, trigram, split16384 | 1.89× | +0.50% | 2.19× | +11.47% |

## Direct paired reference checks on real validation

Each row directly alternates the selected encoder and the named miniz level
in the same worker. These are direct measurements, rather than ratios of
separate benchmark runs.

| Role | Reference | Speed multiple [95% interval] | Size change |
| --- | --- | ---: | ---: |
| speed | miniz1 | 0.40× [0.33, 0.47] | -8.21% |
| balanced | miniz6 | 1.54× [1.26, 1.77] | +2.76% |
| size | miniz9 | 0.70× [0.56, 0.80] | -0.53% |

## Controlled interactions on real training chunks

The factorial crosses probes 1/4/64/512, lazy mode, tails 0/4/16/32,
dual/trigram and splits 1024/16384. Each comparison changes one axis while
holding every other axis fixed. Medians below are across those contexts;
their ranges in the JSON report are context variation, not confidence intervals.

| Axis change | Matched contexts | Median speed multiple | Median size change |
| --- | ---: | ---: | ---: |
| probes: 1 → 4 | 32 | 0.93× | -6.96% |
| probes: 1 → 64 | 32 | 0.48× | -11.52% |
| probes: 1 → 512 | 32 | 0.27× | -12.23% |
| lazy: False → True | 64 | 0.68× | -1.76% |
| insert_tail: 0 → 4 | 32 | 1.06× | +1.19% |
| insert_tail: 0 → 16 | 32 | 1.03× | +0.44% |
| insert_tail: 0 → 32 | 32 | 1.02× | +0.29% |
| index: dual → trigram | 64 | 0.91× | +2.09% |
| block_tokens: 1024 → 16384 | 64 | 1.26× | -2.23% |

The median trigram/dual ratio of the time cost of increasing probes from 1 to 512 is 2.11× across 16 contexts.
Larger probe budgets are not assumed to improve either size or throughput
on every workload.

The p4/greedy/tail16/dual/16384 control matched Fast output bytes on 33 training cases.
Timing differences among equivalent settings reflect representation/codegen
and measurement variation.

## Memory and GPU decision

Memory uses 3 fresh single-encode processes per finalist on the largest
real and synthetic validation cases. Peak RSS includes runtime, input, output
and file I/O; decoding and timing loops run outside these processes. Darwin
units follow the current local getrusage(2) manual (bytes), and the parser
also supports GNU time KiB on Linux. RSS samples/ranges are retained, while
the 192/384 KiB table capacities remain a separate analytical quantity.

| Role | Largest real case median RSS, MiB | Largest synthetic case median RSS, MiB |
| --- | ---: | ---: |
| speed | 73.98 | 2.52 |
| size | 72.05 | 2.52 |
| balanced | 72.52 | 2.53 |

Even deleting the timed CPU setup/proposal/feedback sections entirely would
speed these search runs by at most 1.0010×. This is a generous bound
for replacing those sections, not a trained-surrogate or GPU-encoder result.
The earlier GPU scoring spike still describes kernel capacity only. Model
fitting, context policies and GPU proposal batches need their own evidence.

## Decision and next experiments

Keep the training-selected points as experimental results. This campaign
does not establish a preset promotion: the size guards and production controls
expose transfer failures, and no fresh final test or other hardware was used.

The next S5 baseline should select among fixed configurations and production
presets using cheap workload features, with source/family-grouped cross-validation
and feature/selection overhead charged to encoder time. The five-axis adapter
uses fixed splits and explicit index choices; it does not reproduce Balanced's
classifier or Best's adaptive split callback as configurable policies. Expand
method choices in separate controlled spikes before assuming a stronger
optimizer can recover those behaviors. S7's short encoded-cost oracle can
then test a new parsing hypothesis. Fit a latent/GPU surrogate only after
the simple context baseline has prediction and calibration evidence.

## Evidence and reproduction

[Full report](../scripts/reports/search-campaign.json) links the deterministic
[gzip JSONL ledger](../scripts/reports/search-campaign-measurements.jsonl.gz)
with 15854 candidate rows, raw candidate/baseline rounds and both
stream hashes. Source/binary/corpus hashes, dependency versions, every training
configuration and frozen selection are retained. Packed streams and original
data remain under ignored target/.

The recorded Git parent is `931e97c282ca00759c8431dce2d6e8ce0dd3ef4d`. Measurements include
then-uncommitted research tooling; the source SHA-256 map identifies the
measured files. The parent commit alone does not reproduce this experiment.

Local verification passed 192 feature-enabled Rust tests, 25 research-tool
integrity/adapter tests and 232 unchanged preset stream hashes checked by all
three decoders. Format and all-feature Clippy checks passed. CI additionally
gates the Lean model/axioms, differential/framing harnesses and five fuzz targets.

```sh
make research-check
make research-campaign
python3 scripts/search_campaign_report.py --campaign target/search/campaigns/RUN
```

The optional campaign requires Python 3.12+. `make research-campaign`
installs pinned optional CPU research dependencies in
a local venv and fetches author-hosted corpus archives into target/. Core
runtime dependencies, production policies and the Lean model are unchanged.

3 seeds and 32 unique evaluations per strategy are a bounded comparison. A fresh
final test, additional hardware and memory coverage precede production
promotion. The separate speed, compression and compromise points remain
experimental until those gates are satisfied.
