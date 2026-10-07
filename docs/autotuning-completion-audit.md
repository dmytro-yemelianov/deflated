# Completion audit: automatic encoder tuning investigation

Objective: complete the investigation described in [the design](autotuning-investigation.md),
including negative findings and the evidence needed for each exit decision.
Completed pilots do not establish completion of the whole investigation.

| Requirement | Current authoritative evidence | Remaining work |
| --- | --- | --- |
| S0 measurement contract | Published S0 ledger; corruption, leakage and matrix tests | Retain these gates for every added runner |
| S1 validated knobs and build cache | Config adapter, 232 default-byte witnesses, feature tests and fuzz | Broader history/table/method geometry spike; canonical inactive fields |
| S2 interactions | 128 factorial configurations, matched contexts, raw paired rounds | Extend interactions only for newly introduced methods/layouts |
| S3 optimizer comparison | Three seeds, equal unique budgets: random, mutation, NSGA-II | Mixed-variable Bayesian proposer, matched wall-time/time-to-frontier evidence |
| S4 GPU crossover | Untrained kernel plus [trained fitting/scoring](trained-surrogate-report.md); 880-row CPU fallback, retained failed fitting-parity gate | Whole-loop verified proposal comparison; large-batch crossover is not a search speedup |
| S5 context policy | [Native policy report](context-policy-report.md): 663 paired rows, nested grouped CV, fresh validation, native selection cost, three decoders, sampling-trap and native parity/parser gates | Bounded spike complete: no general improvement over fixed presets; carry size tree to frozen S9 comparison without production promotion |
| S6 latent representation | [Trained surrogate report](trained-surrogate-report.md): 10659 unique labels; trees versus explicit/latent ensembles, source/family and config holdout, group calibration, raw predictions/checkpoints | Bounded spike rejected: trees predict/rank better, intervals too wide, no reduced encoder evaluations; retain CPU baseline for S3 whole-loop study |
| S7 encoded-cost parsing | No exact oracle or beam prototype | Short exact cost oracle, bounded parsing prototype, actual encoded-size/CPU results and validity checks |
| S8 mixed-block emission | Existing whole-input stored fallback only | Header/alignment-aware stored/fixed/dynamic experiment and Lean emitter scope review |
| S9 validation/portability | M5 seven-round regression pilot and two-case RSS | Frozen finalists, fresh workloads, ten longer paired sessions with warm/cold scope, decode/tiny-input/binary-size/memory guardrails and available portability evidence |
| Synthetic extensions | Nine original families, boundary stress, S5 Zipf bursts/Markov/template edits with disjoint regimes | Cost-sensitive matches, candidate-hash collisions, change points/drift, repeated wraps/position simulation, paired transforms |
| Publication and verification | S5 main commit 0c81887; CI 37580753441 succeeded; S6 local data/artifact checks pass | Publish subsequent artifacts with raw observations, provenance, failures, explicit decisions and applicable correctness gates |

The public reserved synthetic test remains unmeasured. Previously visible real
holdout data is regression evidence. New policies and methods must be frozen
before fresh final-test measurements. No cloud compute is part of the design.

## Active sequence

1. S5/S6 evidence is exported; run publication and correctness gates.
2. S3/S4: verified Bayesian proposal comparison, matched wall-time/frontier
   evidence and whole-loop GPU decision using the retained negative S6 result.
3. Broader geometry, S7/S8 and generator extensions: introduce methods through
   isolated research paths, with model review where emission semantics change.
4. S9: freeze all finalists and criteria, run final/portability gates, record
   promotion or rejection, then audit every row above against actual artifacts.

This file tracks open work. The goal remains active until evidence closes every
required deliverable; an unfavorable experimental outcome is a valid exit only
when the corresponding experiment and verification have actually run.
