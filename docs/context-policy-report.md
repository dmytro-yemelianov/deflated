# S5: workload-conditioned policies with charged native selection

This experiment measures a frozen 11-method vocabulary on 39 training cases,
fits bounded integer-feature trees using nested grouped validation, freezes
the policies, then measures them on 39 validation cases. The original 14
synthetic tests, six new synthetic tests and six Calgary files remain reserved.

Vocabulary selection used the prior S2/S3 training evidence. Nested CV is
conditional on that vocabulary. Previously visible full real files are
regression evidence; seven Calgary files and six generated cases are separate
fresh validation. Calgary pic was excluded because it duplicates an earlier
source. Source/archive/payload hashes and an approximate sampled-shingle
near-copy check are retained. [Corpus source](https://corpus.canterbury.ac.nz/descriptions/).

## Selection and feature cost

Thirteen integer features use at most 4096 staggered samples: length class,
symbol concentration, equality at six lags, printable bytes and zeros.
Rust/Python/manifest vectors must match exactly. Below 32 KiB the policy
returns Balanced before feature extraction. Constant policies also skip
feature extraction. Nonconstant features and selection run inside each
timed native encode, together with allocation and emission.

Five outer source/family folds evaluate selection; three inner folds choose
depth -1/0/1/2/3, with at least three cases in a leaf. Depth -1 is the
Balanced control. Held outer targets do not choose that fold's tree or depth.
Leaves minimize summed paired-B-normalized encoder time subject to per-case
training size bounds (+20% speed, +1% compromise), or exact summed size
for the size role. CV also rejects aggregate/per-file regressions. CV scores
estimate encoder cost from labels; the native measurements below include
the additional policy cost. Every policy output hash must match an independently
encoded Python-selected leaf, as well as passing all three decoders.

| Role | Final depth | Nested estimated speed | Nested size change | Nested guards |
| --- | ---: | ---: | ---: | --- |
| speed | 0 | 1.30× | +1.24% | pass |
| balanced | -1 | 1.00× | +0.05% | pass |
| size | 1 | 0.49× | -0.19% | pass |

## Previously visible full real files

| Method | Speed vs paired Balanced [95% interval] | Size change |
| --- | ---: | ---: |
| policy-speed | 1.27× [1.14, 1.39] | +1.82% |
| policy-balanced | 1.02× [0.94, 1.12] | +0.00% |
| policy-size | 0.57× [0.49, 0.70] | -0.62% |
| balanced | 1.00× [0.98, 1.01] | +0.00% |
| fast | 1.86× [1.57, 2.16] | +5.73% |
| best | 0.56× [0.45, 0.72] | -0.62% |

## Fresh Calgary validation

| Method | Speed vs paired Balanced [95% interval] | Size change |
| --- | ---: | ---: |
| policy-speed | 1.06× [1.04, 1.20] | +2.41% |
| policy-balanced | 1.01× [0.99, 1.05] | +0.00% |
| policy-size | 0.76× [0.63, 0.78] | -0.38% |
| balanced | 1.00× [0.98, 1.01] | +0.00% |
| fast | 2.12× [1.77, 2.30] | +6.04% |
| best | 0.75× [0.59, 0.77] | -0.38% |

## Previous synthetic validation

| Method | Speed vs paired Balanced [95% interval] | Size change |
| --- | ---: | ---: |
| policy-speed | 1.21× [0.99, 1.84] | -0.58% |
| policy-balanced | 0.99× [0.96, 1.07] | +0.00% |
| policy-size | 0.68× [0.47, 0.96] | -2.20% |
| balanced | 1.00× [0.97, 1.04] | +0.00% |
| fast | 1.20× [0.74, 2.56] | +2.79% |
| best | 0.48× [0.33, 0.69] | -0.46% |

## Fresh synthetic regimes

| Method | Speed vs paired Balanced [95% interval] | Size change |
| --- | ---: | ---: |
| policy-speed | 1.37× [1.06, 2.18] | +1.40% |
| policy-balanced | 1.00× [0.99, 1.01] | +0.00% |
| policy-size | 0.59× [0.28, 0.78] | -0.36% |
| balanced | 1.00× [0.99, 1.01] | +0.00% |
| fast | 2.14× [1.86, 4.15] | +4.18% |
| best | 0.61× [0.28, 0.83] | -0.37% |

## Evidence and decision scope

The speed role chose a constant 16-probe lazy trigram method with full insertion;
the compromise chose Balanced. These results do not support useful context
adaptation for either role. All three policies pass their predeclared validation
size guards in each scope; the fixed Fast control exceeds the +20% per-file
limit on synthetic data. Validation does not refit or reselect policies.

The size tree chooses the 1024-probe trigram method when the largest sampled
symbol count is at most 273, and Best otherwise, with the small-input fallback.
On real files it mostly chooses Best. Its output is slightly larger than Best
in both real scopes; the speed intervals overlap, and these are separate
paired-B sessions rather than a direct tree-versus-Best timing experiment.
Its previous synthetic scope is smaller than Best; fresh synthetic output
is slightly larger. This is a bounded synthetic tradeoff, with no demonstrated
general improvement over Best. Keep the production presets unchanged.

| Scope | Size tree output change vs Best |
| --- | ---: |
| real-regression | +0.0014% |
| real-fresh | +0.0015% |
| synthetic-regression | -1.7523% |
| synthetic-fresh | +0.0086% |

[Full evidence](../scripts/reports/search-policy.json) retains fold membership,
all training labels, chosen depths, frozen trees, native policy text, source
and binary provenance. The [raw gzip ledger](../scripts/reports/search-policy-measurements.jsonl.gz)
contains 663 candidate/baseline measurement rows. Five training
rounds use at least 5 ms batches; seven validation rounds use at least 10 ms.
Confidence intervals resample source/family groups and paired rounds.

The Git parent predates then-uncommitted research changes; the recorded source
SHA map identifies the measured files. Core runtime dependencies and the Lean
model are unchanged. Policy RSS, longer warm/cold sessions, decode/tiny-input
and binary-size guardrails, latent prediction and final-test results remain
subsequent investigation work, tracked by the completion audit.

```sh
make research-policy-check
make research-policy
python3 scripts/search_policy_report.py --campaign target/search/policies/RUN
```
