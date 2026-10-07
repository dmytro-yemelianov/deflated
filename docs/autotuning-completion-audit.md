# Completion audit: automatic encoder tuning investigation

Objective: complete the investigation described in [the design](autotuning-investigation.md),
including negative findings and the evidence needed for each exit decision.
Completed pilots do not establish completion of the whole investigation.

| Requirement | Current authoritative evidence | Remaining work |
| --- | --- | --- |
| S0 measurement contract | Published S0 ledger; corruption, leakage and matrix tests | Retain these gates for every added runner |
| S1 validated knobs and build cache | Config adapter, 232 default-byte witnesses; [eight isolated hash/history layouts](encoded-cost-report.md), source/compiler/flags keyed builds, canonical inactive preset fields | Bounded geometry spike complete; no production layout change or claim that every proposed knob was implemented |
| S2 interactions | 128 factorial configurations plus [parser/layout regimes](encoded-cost-report.md) and [preset × token limit × emission](mixed-block-report.md), matched contexts and raw paired rounds | Bounded interaction studies complete; no exhaustive optimum claim |
| S3 optimizer comparison | [Bayesian report](bayesian-search-report.md): fresh three-seed random/NSGA-II/MOTPE, 10692 verified paired rows, equal unique and observed wall-time budgets, censored time-to-frontier | Bounded comparison complete; carry training finalists to frozen S9 without promotion |
| S4 GPU crossover | [Trained fitting/scoring](trained-surrogate-report.md) plus actual [whole-loop accounting](bayesian-search-report.md); CPU fallback at 880 candidates | Bounded spike rejected: fit parity failed, latent prediction/calibration failed, optimizer-replacement upside at most 0.15%; no unsupported GPU search speedup |
| S5 context policy | [Native policy report](context-policy-report.md): 663 paired rows, nested grouped CV, fresh validation, native selection cost, three decoders, sampling-trap and native parity/parser gates | Bounded spike complete: no general improvement over fixed presets; carry size tree to frozen S9 comparison without production promotion |
| S6 latent representation | [Trained surrogate report](trained-surrogate-report.md): 10659 unique labels; trees versus explicit/latent ensembles, source/family and config holdout, group calibration, raw predictions/checkpoints | Bounded spike rejected: trees predict/rank better, intervals too wide, no reduced encoder evaluations; retain CPU baseline for S3 whole-loop study |
| S7 encoded-cost parsing | [Exact oracle and native bounded DP](encoded-cost-report.md): 128 native/Python witnesses, exhaustive binary inputs through eight bytes, 1456 paired rows and three decoders | Bounded spike complete and rejected for production Best: high CPU cost and worst-file guard failures; frozen roles retain Balanced/Best |
| S8 mixed-block emission | [Eight-offset native DP](mixed-block-report.md): 2184 paired rows, 21 methods, matched compressed-only controls; exhaustive type sequences, all-offset stored packets and three decoders; Lean scope reviewed | Bounded spike rejected for production replacement; no general improvement over Balanced/Best, mixed append outside current encoder theorem |
| S9 validation/portability | M5 seven-round regression pilot and two-case RSS | Frozen finalists, fresh workloads, ten longer paired sessions with warm/cold scope, decode/tiny-input/binary-size/memory guardrails and available portability evidence |
| Synthetic extensions | Original families, S5 Zipf/Markov/template edits; [new cost, three collision, change/drift, sampling-trap and paired-transform families](encoded-cost-report.md), 27 train/18 validation/18 reserved cases; native repeated wraps and arithmetic 4GiB-boundary simulation | Generator spike complete; the arithmetic simulation is not a native 4GiB encode or a 32-bit Rust proof |
| Publication and verification | S5 CI 37580753441, S6 CI 37582002781 and S3 CI 37583954135 succeeded; S7/S8 artifacts and mandatory native gates added | Publish subsequent artifacts with raw observations, provenance, failures, explicit decisions and applicable correctness gates |

The public reserved synthetic test remains unmeasured. Previously visible real
holdout data is regression evidence. New policies and methods must be frozen
before fresh final-test measurements. No cloud compute is part of the design.

## Active sequence

1. S3/S4/S5/S6 bounded evidence is exported; retain publication and correctness gates.
2. S1 geometry/S7/S8/generator evidence is exported with negative production
   decisions and explicit model boundaries; retain native and artifact gates.
3. S9: freeze all finalists and criteria, run final/portability gates, record
   promotion or rejection, then audit every row above against actual artifacts.

This file tracks open work. The goal remains active until evidence closes every
required deliverable; an unfavorable experimental outcome is a valid exit only
when the corresponding experiment and verification have actually run.
