# S9: frozen final tuning validation

Measured on Apple M5 (arm64), rustc 1.88.0 (6b00bc388 2025-06-23).
The direct encoder reference is the locked dev-dependency miniz_oxide
0.8.9 at raw DEFLATE levels 1/6/9. Every reference measurement is made
inside this study; historical baseline figures are not substituted.
Eleven methods were frozen before encoding 44 reserved cases (six fresh
Calgary sources and 38 synthetic cases) and 19 tiny inputs. Ten complete
sessions rotate files, methods and candidate/baseline order. Warm batches
last at least 20 ms (2 ms for tiny inputs). Encoder allocation, matching,
policy selection and emission are included; input I/O and oracle checks
are excluded. Decoder timings use deflate-core for every encoder’s output.

Cold observations are first calls in separate fresh processes with
resident input and parsed policy. They include fresh encoder/decoder
allocations, exclude startup and input I/O, and do not represent cold OS,
disk or instruction caches. Every candidate/baseline packet agrees across
sessions and warm/cold paths and passes three decoders. No final-test
feedback changes the candidates, policies, budgets or thresholds.

An earlier 3015-row attempt was stopped when file rotation was found
to cancel method/pair rotation. Its source hashes and raw observations
remain in the [aborted report](../scripts/reports/search-final-aborted.json).
Those observations are excluded from final claims. The corrected
schedule covers ten distinct method positions and five candidate-first
and five baseline-first pairs for every fixed input/method.

## Fresh aggregate

| Method | Median warm speed vs paired Balanced | Session mean [95% CI] | Median cold speed | Packed-size change | Worst file ratio |
| --- | ---: | --- | ---: | ---: | ---: |
| fast | 1.404× | 1.357× [1.306, 1.399] | 1.390× | +4.347% | 2.180× |
| balanced | 1.002× | 1.006× [1.000, 1.013] | 1.001× | +0.000% | 1.000× |
| best | 0.351× | 0.355× [0.352, 0.358] | 0.356× | +0.252% | 1.155× |
| miniz1 | 10.167× | 10.087× [9.921, 10.227] | 9.512× | +4.657% | 2.773× |
| miniz6 | 1.315× | 1.326× [1.318, 1.337] | 1.315× | -0.343% | 1.018× |
| miniz9 | 0.624× | 0.628× [0.615, 0.641] | 0.622× | -0.468% | 1.016× |
| bayesian-speed | 2.559× | 2.465× [2.349, 2.543] | 2.499× | +3.287% | 1.950× |
| bayesian-compromise | 1.576× | 1.544× [1.485, 1.581] | 1.567× | +0.901% | 1.456× |
| bayesian-size | 0.788× | 0.790× [0.786, 0.794] | 0.790× | -0.065% | 1.003× |
| policy-speed | 1.356× | 1.334× [1.277, 1.374] | 1.348× | +0.635% | 1.207× |
| policy-size | 0.458× | 0.465× [0.458, 0.479] | 0.461× | -0.306% | 1.002× |

Throughput ratios use summed per-file medians. Session bootstrap
confidence bounds apply to pooled paired session-mean ratios, whose
point estimates are separately reported. Guard decisions use those
predeclared session bounds; these two estimators are kept distinct.

Session confidence describes repeat noise on these fixed cases. It
does not establish generalization to another population or machine.
The JSON separates real/synthetic/family scopes and per-file medians.

## Direct native references on the same fresh cases

| Frozen role candidate / miniz level | Warm speed vs reference | Packed-size change from reference |
| --- | ---: | ---: |
| bayesian-speed / miniz1 | 0.253× | -1.309% |
| bayesian-compromise / miniz6 | 1.204× | +1.248% |
| bayesian-size / miniz9 | 1.260× | +0.404% |
| policy-speed / miniz1 | 0.134× | -3.843% |
| policy-size / miniz9 | 0.734× | +0.162% |

Direct comparisons pair the same input/session and preserve the
actual native reference encoder timings.

## Decode, tiny-input, memory and linked-size gates

Three separate `/usr/bin/time` single-encode repetitions per method cover
the largest reserved input, largest fresh real file and largest previous
full real file. Darwin RSS is measured in bytes; Linux parsing converts
KiB to bytes. The prior full file is memory-only regression evidence.
Peak RSS includes the process, resident input, tables, temporaries and
output; it is not reported as encoder-only heap.

All 22 release/min linked probes were built before timing and their
packets match the main worker on a private verification input. Sizes
include external policy payloads and retain the shared runtime parser.
The min profile is measured for size only, not advertised for speed.

| Candidate | Failed measured guards | Maximum tiny warm latency ratio | Maximum RSS increase | Release probe increase |
| --- | --- | ---: | ---: | ---: |
| bayesian-speed | maximum_file_size | 1.090× | 1703936 B | 0 B |
| bayesian-compromise | maximum_file_size | 1.080× | 278528 B | 0 B |
| bayesian-size | aggregate_size | 0.940× | -573440 B | 0 B |
| policy-speed | maximum_file_size | 1.026× | -49152 B | 73 B |
| policy-size | none | 1.026× | 16384 B | 96 B |

Thresholds were frozen in the protocol before final encoding. Size
roles use Best for speed/decode/tiny/RSS/linked-size comparisons; speed
and compromise use Balanced. Both warm/cold session confidence bounds
must pass encoder and decoder limits. The tiny guard checks the worst
per-input warm median, so large files cannot conceal tiny regressions.

## Decision

- **bayesian-speed:** reject production promotion; retain measured tradeoff.
- **bayesian-compromise:** reject production promotion; retain measured tradeoff.
- **bayesian-size:** reject production promotion; retain measured tradeoff.
- **policy-speed:** reject production promotion; retain measured tradeoff.
- **policy-size:** retain opt-in research profile; no default change or production integration claim.

Production defaults remain unchanged. Existing Lean model theorems
cover checked finder/token and fixed/dynamic/whole-stored policies,
not heuristic quality, runtime speed or a Rust refinement. S7 and S8
remain rejected isolated prototypes with documented model boundaries.

The [new-packet correspondence ledger](../scripts/reports/search-final-correspondence.json) also checks 439 packets through
the actual Lean and Rust CLI decoders: every S7 exact and S8 mixed
witness plus every S9 fresh real/tiny output. Decoded lengths/hashes
match the input and timed packet hashes. This is finite model evidence.

The measured [size policy](../scripts/reports/final-size.policy) passes
the predeclared guards and improves on Best on this fixed mixed set.
It is still dominated by miniz6 in the aggregate speed/size comparison;
passing internal guards does not establish superiority over references.
Use it only as an opt-in research profile:

```sh
cargo build --locked --release -p deflate-core --example final_bench --features research-tuning
target/release/examples/final_bench --memory INPUT.raw OUTPUT.deflate policy@scripts/reports/final-size.policy
```

[Report](../scripts/reports/search-final.json) and [raw ledger](../scripts/reports/search-final-measurements.jsonl.gz) retain 6930 paired rows,
all session observations, corpus membership, source/build/policy hashes,
RSS tool output, linked probe counts, reference comparisons and failures.

```sh
make research-final-check
python3 scripts/search_final_campaign.py --out target/search/final/RUN
python3 scripts/search_final_correspondence.py --campaign target/search/final/RUN
python3 scripts/search_final_report.py --campaign target/search/final/RUN
```
