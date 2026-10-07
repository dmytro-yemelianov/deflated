# S3: verified mixed-variable Bayesian search and wall-time frontiers

This campaign compares fresh random, NSGA-II and multivariate MOTPE runs
on the same native binary and 33 mixed training cases. Each strategy has
32 unique configured evaluations across the same three seeds. Strategy
order rotates; native measurements are serial, with other heavy local
work paused. Each case uses five paired rounds with 5 ms minimum batches.
Both candidate and Balanced streams pass three decoders. Reserved final
tests and validation data are never encoded by this campaign.

[Optuna 4.5 MOTPE](https://optuna.readthedocs.io/en/v4.5.0/reference/samplers/generated/optuna.samplers.TPESampler.html)
uses 12 startup trials and 64 acquisition candidates, with multivariate
group decomposition. Probe counts are log2 integers; lazy/index/token splits
are categorical. Full insertion masks an inactive log2 tail field. This
maps bijectively to the same 880 configurations as categorical NSGA-II
and random search. Repeated proposals reuse verified feedback without
charging another unique evaluation; cache hits remain recorded.

## Evaluation budget and observed wall-time comparison

Hypervolume minimizes normalized paired encoder time and exact size with
a fixed (4, 1.5) reference and (1, 1) anchor. Presets/Stored are excluded
from the optimizer frontiers. Wall time begins after the common four
control encodes and includes optimizer setup, ask/cache/feedback, native
encoding, three-decoder checks, source/corpus guards and ledger I/O.
Compilation and controls are separately retained in the report.

The common observed horizon is 101.33 seconds,
the shortest completed configured-search clock. A result contributes only
after its complete verification. Fixed checkpoints use only times observed
in every run; stopped runs are never extrapolated.

| Strategy | 32-evaluation HV median [range] | Common-time HV median [range] | Common-time evaluations median [range] |
| --- | ---: | ---: | ---: |
| random | 1.8038 [1.7817, 1.8082] | 1.8038 [1.7817, 1.8082] | 29 [27, 31] |
| nsga2 | 1.8161 [1.7529, 1.8204] | 1.8142 [1.7529, 1.8198] | 29 [28, 29] |
| tpe | 1.8303 [1.8206, 1.8447] | 1.8247 [1.8206, 1.8447] | 31 [29, 32] |

## Time to predeclared hypervolume targets

| Strategy / seed | HV 1.75, seconds | HV 1.8, seconds | Search duration, seconds |
| --- | ---: | ---: | ---: |
| random / 195108 | 6.45 | not reached (censored) | 115.09 |
| nsga2 / 195108 | 75.67 | 100.37 | 109.04 |
| tpe / 195108 | 2.78 | 69.76 | 108.62 |
| nsga2 / 195109 | 9.02 | 94.12 | 113.14 |
| tpe / 195109 | 14.99 | 47.73 | 101.33 |
| random / 195109 | 28.21 | 91.02 | 104.56 |
| tpe / 195110 | 42.60 | 47.99 | 101.99 |
| random / 195110 | 38.53 | 94.84 | 110.34 |
| nsga2 / 195110 | 76.68 | not reached (censored) | 109.62 |

Three seeds support a bounded comparison; retain the ranges and avoid
claiming statistical superiority. The configurations selected here still
need frozen S9 validation before any production promotion.

In this pilot MOTPE has the highest median frontier at both matched
budgets and reaches HV 1.8 in all three seeds (47.7–69.8 seconds).
Random and NSGA-II reach that target in two seeds each, with the other
runs censored. Use CPU MOTPE as an additional research baseline; this
supports better proposal selection here, not encoder superiority on fresh
data. Keep all three strategies available for subsequent method spaces.

## Whole-loop GPU decision

S6 found worse latent prediction/ranking than explicit trees, overly wide
calibration and a failed fitting-parity guard. Strict scoring passed but
CPU was faster at 880 candidates. Here the actual CPU proposer fraction
bounds the upside even if its entire setup/ask/feedback vanished.

| Strategy | Optimizer fraction, median [range] | Instantaneous replacement bound, maximum |
| --- | ---: | ---: |
| random | 0.003% [0.002, 0.003] | 1.0000× |
| nsga2 | 0.113% [0.100, 0.128] | 1.0013× |
| tpe | 0.142% [0.111, 0.145] | 1.0015× |

This is a measured whole-loop accounting bound, not a hypothetical
trained-GPU speedup. GPU model fitting/conversion would add cost. Keep
CPU proposal fallback for this workload; no GPU encoder is implemented.

[Full evidence](../scripts/reports/search-bayesian.json) preserves canonical
configs, raw optimizer records, per-trial completion clocks, frontiers,
censoring, frozen training finalists and source/binary provenance.
The [paired gzip ledger](../scripts/reports/search-bayesian-measurements.jsonl.gz) contains 10692 rows.
Git parent predates then-uncommitted search-tool changes; source hashes
identify the measured revision. Production core/Lean sources are unchanged.

```sh
target/search/optimizer-venv/bin/python scripts/search_bayesian_campaign.py --out target/search/bayesian/RUN
python3 scripts/search_bayesian_report.py --campaign target/search/bayesian/RUN
```
