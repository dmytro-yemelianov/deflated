# New compression methods: closure report

Status: closed by maintainer decision on 2026-10-07. Active R&D ended; the
existing project is in maintenance mode. The original G0–G6 objective was only
partially executed. No new production path or format is promoted. The
[handover](handover.md) records maintenance and reproduction details.

## Completed B training screen

One randomized serial training session completed 40 cases × 73 methods =
**2,920 rows**, with no restart or replacement. Cases were eight real B training
groups, ten structured synthetic training cases, one separate 8 MiB structured
stress case, twelve shared tiny witnesses and nine shared boundary witnesses.
Scopes remain separate. No validation/held codec screen, fitting or final
independent evaluation was performed.

The roster comprises 41 native settings, 18 core/miniz settings, 12 DSC1
configurations and two same-framing plain DSC1 controls. The sealed controls
cover zlib, zlib-ng, libdeflate, zstd, LZ4/LZ4-HC, Brotli and LZMA2, plus core
and miniz. DEFLATE is measured in raw/gzip/ZIP; cross-format comparisons use
the complete frames in the [worker contract](new-methods-benchmarking.md).
OpenZL was excluded after its two bounded setup attempts and has no measured
result. The fixed roster and source pins were not selected after seeing results.

Encode pays scanner/dictionary selection, substream compression, reconstruction
checking, CRC, original DEFLATE/raw alternatives and final selection. All codec
state/output allocation and framing are charged. Input I/O and independent
verification are outside codec timers. Warm batches are at least 20 ms, or
2 ms for tiny cases. First-call decode uses a separate decoder-only process
with zero encoder calls; paired workers' post-encode decode field is not used
as cold decoder timing. Every packet was independently decoded byte-exactly.

## Negative result

No setting passes the preregistered training point guards. The selection rule
returns no sentinel, so the initial B family is rejected before validation.
The best primary-size candidate is
`dsc1:18/all-quoted/checked-delta:frame`:

| Primary B training metric | Observed | Required B-size target |
| --- | ---: | ---: |
| Complete bytes vs checksummed zstd-3 | 357,540 / 329,478 = 1.08517× | ≤0.95× |
| Bytes vs own untransformed frame | 357,540 / 360,226 = 0.99254× | ≤0.98× |
| Largest primary file ratio vs zstd-3 | 1.26068× | ≤1.10× |
| Warm encode throughput vs zstd-3 | 0.02592× (38.58× slower) | ≥0.25× |
| First-call encode throughput vs zstd-3 | 0.04061× (24.63× slower) | ≥0.25× |
| Warm decode time vs zstd-3 | 21.694× | ≤3× |
| First-call decode time vs zstd-3 | 13.301× | ≤3× |

The fastest B setting, `dsc1:18/off/checked-delta:frame`, still has only
0.03150× zstd-3 warm encode throughput (31.75× slower) and 1.09297× its bytes.
No candidate meets the compromise stretch target either. For the best-size
candidate, the largest shared-tiny encode/decode time ratio is 168.98× versus
the ≤2× guard. Complete per-method/per-scope sums and individual rows are
published; these examples are not a selected winning scope.

These are **one-session training point estimates**, without confidence
intervals or a fresh holdout result. Formal targets required confidence bounds
at confirmation. Failing the early screen justifies stopping this family; it
does not prove that every possible structured codec must fail. The transform
saves only 0.75% versus its own plain control here. The implementation also
pays a baseline DEFLATE alternative and reconstruction work. That design
observation is not a new profile attributing exact runtime shares.

## Stage disposition

| Stage | Final disposition |
| --- | --- |
| G0: baseline, prior work, direct controls | Complete; b7, native/Rust reference and decoder-only locks retained; OpenZL excluded explicitly |
| G1: fresh source groups and stress | Complete; 36 source groups, 99 generated cases and historical regression index frozen/audited |
| G2: matcher | Cancelled before implementation; 12 equivalent and eight coverage configurations untested |
| G3: DSC1 | Independent decoder, normative vectors and Rust prototype implemented; all 12 settings screened and rejected; no sentinel |
| G4: correctness/proofs | Finite cross-language vectors, mutations, strict consumption contracts and bounded fuzz retained; full DSC1 transform/frame model and A correspondence not completed |
| G5: validation/final holdout/resources | Not run; no finalist, confidence bounds, new-study RSS qualification or final performance claim |
| G6: integration/report/GPU | No promotion; evidence and closure published; GPU work not justified by measured loop accounting |

The remaining A tasks were cancelled by the maintainer, not resolved through
a negative experiment. The G5 and proof gaps are explicit waivers of continued
work at closure, not passing gates. The core/Rust suffix contract, default
compression path and b7-compatible packets retain their existing behavior.
G0 measured host-specific CLI sizes, but those facts do not pass every G5
resource gate. Lean theorems remain model statements without Rust refinement.
No DSC1 production verification or research novelty is claimed. See
[related work](new-methods-related-work.md) before describing fingerprints,
dictionaries, delta coding or stream separation as inventions.

The earlier completed [encoder investigation](encoder-improvement-report.md)
retained a separate 1.032× warm default improvement with identical packets.
This new campaign added no qualified performance improvement.

## GPU decision and artifacts

The measured B loop took 231.66 s. Proposal/planning and selection used
0.0343 s, **0.0148%** of the loop, below the frozen 5% trigger. There was no
surrogate fitting, GPU workload or cloud spending. Eliminating all of this
proposal/selection work would barely change the measured loop. This supports
not pursuing GPU proposals for this screen; it does not measure GPU encoding.
A-specific GPU accounting was cancelled with A.

Published evidence:

- [Intent and complete roster](../scripts/reports/new-methods-b-training-intent.json.gz)
- [Raw 2,920-row ledger](../scripts/reports/new-methods-b-training-rows.jsonl.gz)
- [All five scope aggregates](../scripts/reports/new-methods-b-training-scopes.json)
- [All 12 candidates and selection](../scripts/reports/new-methods-b-training-summary.json)
- [Completion state and content hashes](../scripts/reports/new-methods-b-training-status.json)
- [Immutable reference lock](../scripts/reports/new-methods-reference-lock.json)
- [Decoder-only supplement lock](../scripts/reports/new-methods-decoder-lock.json)
- [Data and regression audit](../scripts/reports/new-methods-data-audit.json)

The publication audit binds source/protocol/reference/data hashes, the exact
73×40 roster, timer fields, decoder-only zero-encode contracts, scope sums and
the rederived negative selection. It audits existing rows without rescreening:

```sh
python3 scripts/new_methods_b_publish.py --check
# Original local cache only: also verify each raw input and encoded packet.
python3 scripts/new_methods_b_publish.py --check --local
```

Sealed local directories refuse replacement; use fresh paths for reproduction.
Historical evidence and unrelated local files were preserved. Closure validation
is the artifact audit plus CI on the closure revision; the prior passing
[dfb3724 run](https://github.com/dmytro-yemelianov/deflated/actions/runs/37679215741)
establishes the preceding source state only. Current runs are available in the
[CI workflow](https://github.com/dmytro-yemelianov/deflated/actions/workflows/ci.yml).
