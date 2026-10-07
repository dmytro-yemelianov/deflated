# S6: trained explicit and latent encoder surrogates

The training ledger contains 10659 unique file/config labels:
33 training cases, 323 observed configurations, 21 source/family groups.
Repeated measurements are collapsed to median log paired time ratios;
exact packed sizes and hashes must agree. Features use only the training
cases from S5. Neither prior validation targets nor reserved tests feed
training, normalization or calibration.

Three outer partitions each hold out seven complete source/family groups.
Five additional groups calibrate uncertainty; the remaining nine fit models.
A deterministic 65-config holdout is absent from both fitting and calibration.
Held groups are scored on every observed configuration, including those
unseen combinations. This is a joint extrapolation diagnostic. Parameters
were frozen before fitting; there is no held-target hyperparameter sweep.

Inputs contain 13 scaled integer workload features and categorical method
and parameter indicators. Presets mask inactive configured axes. The
baseline is 64 [Extra Trees](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html)
with at least three rows per leaf. Explicit neural ensembles directly mix
features and config indicators. Latent ensembles first learn a 16-dimensional
workload bottleneck, then mix it with configuration indicators in a 128-wide
hidden layer. Four members use group bootstrap and 800 minibatch Adam updates.
The learned representation encodes sampled features, not raw input bytes.

## Held prediction and ranking

| Model | Group mean absolute log error, time / size | Mean Spearman, time / size | Top-32 overlap, time / size | Whole-group interval coverage | Mean fold half-width, log time / size |
| --- | ---: | ---: | ---: | ---: | ---: |
| trees | 0.375 / 0.076 | 0.838 / 0.713 | 0.658 / 0.425 | 85.7% | 6.662 / 1.379 |
| explicit | 0.514 / 0.194 | 0.775 / 0.549 | 0.528 / 0.295 | 100.0% | 26.527 / 10.750 |
| latent | 0.427 / 0.127 | 0.756 / 0.581 | 0.532 / 0.293 | 81.0% | 14.011 / 3.494 |

Errors are in log ratios, so they are not percentage-point errors.
Ranking averages weight each case equally; size ties are ranked with
average ranks for correlation and stable config-ID order for top-32 overlap.
All raw member predictions, targets and interval widths are retained.

Uncertainty is ensemble spread with a 0.02 log-unit floor. Calibration
uses the maximum joint standardized residual in each of five calibration
groups and the finite-sample corrected 80% quantile. This can produce
wide intervals. Coverage and width must be read together; neither small
corpus exchangeability nor unseen-configuration coverage is guaranteed.

Here the calibrated intervals are too wide for useful acquisition: even
the tree model has mean time half-widths above five log units. High row
coverage is therefore not evidence of a precise uncertainty estimate.

## Trained CPU / Metal measurements

The same trained first-fold latent network is scored with strict float32
([MLX precision](https://ml-explore.github.io/mlx/build/html/usage/precision.html),
[gradient transform](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.value_and_grad.html)).
Inputs and weights are materialized, each device warmed twice, order rotated,
and evaluation/synchronization completed before stopping the clock.
The diagnostic ranking uses mean minus 0.1 spread; it is not an acquisition
or a claimed compression result. Timing includes host result transfer.

| Batch | CPU median, ms | GPU median, ms | GPU speed | Numeric check | Top-32 overlap |
| --- | ---: | ---: | ---: | --- | ---: |
| 16 | 0.096 | 0.752 | 0.13× | pass | 100.0% |
| 880 | 0.289 | 0.471 | 0.61× | pass | 100.0% |
| 4096 | 1.068 | 1.901 | 0.56× | pass | 100.0% |
| 65536 | 20.464 | 10.592 | 1.93× | pass | 100.0% |

Repeated fitting: CPU 0.51 s, GPU 0.39 s, GPU 1.30×.
Three rotated repeats use identical initialization/bootstrap/minibatches.
The clock charges initialization, conversion, bootstrap and 800 updates.
CPU/GPU fitted prediction scaled error: 0.0569; predeclared 0.005 check fails.

## Decision scope

The latent bottleneck improves absolute prediction error over the explicit
neural model, but the trees are better on both objective errors and ranking.
It fails the declared prediction/ranking/calibration case for replacing
the explicit baseline. No encoder-evaluation saving has been demonstrated.
The repeated CPU/GPU fitting discrepancy fails its predeclared numeric
guard; retain that failed result and reject fitting parity. Scoring the
same trained parameters passes. At 880 candidates CPU scoring is faster;
the 65536-row GPU crossover does not justify GPU use in this search space.
Device speed alone does not establish better proposals, fewer encoder
evaluations, or a whole-search speedup. These observations evaluate already
verified configurations; actual proposals still require native encoder and
three-decoder checks. Keep CPU proposal machinery and production presets
until a matched-budget whole-loop experiment supplies that evidence.

[Full report](../scripts/reports/search-surrogate.json),
[raw predictions](../scripts/reports/search-surrogate-predictions.jsonl.gz),
and [trained neural checkpoints](../scripts/reports/search-surrogate-models.zip)
retain partitions, calibration scores, model hashes, device/library versions
and raw fitting/scoring rounds. Source hashes identify the then-uncommitted
research scripts. The original encoder evidence remains authoritative for
measured time/bytes; model outputs never replace it.

```sh
python3 -m venv target/search/surrogate-venv
target/search/surrogate-venv/bin/python -m pip install -r scripts/surrogate-requirements.txt
target/search/surrogate-venv/bin/python scripts/search_surrogate.py --out target/search/surrogate/RUN
python3 scripts/search_surrogate_report.py --campaign target/search/surrogate/RUN
```
