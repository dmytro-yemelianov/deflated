# Completion audit: automatic encoder tuning investigation

Objective: complete the investigation described in [the design](autotuning-investigation.md),
including negative findings and the evidence needed for each exit decision.
The bounded S0–S9 experiments have run, including the frozen final evaluation.
An unfavorable result is an exit decision supported by measurements, not a
claim that every possible algorithm or parameter combination has been exhausted.

| Requirement | Current authoritative evidence | Outcome and boundary |
| --- | --- | --- |
| S0 measurement contract | Published S0 ledger; corruption, leakage and matrix tests; source/binary/corpus and decoder guards retained in added runners | Contract applied to completed campaigns; final matrix and genuine session rotation reconstruct from raw observations |
| S1 validated knobs and build cache | Config adapter, 232 default-byte witnesses; [eight isolated hash/history layouts](encoded-cost-report.md), source/compiler/flags keyed builds, canonical inactive preset fields | Bounded geometry spike complete; no production layout change or claim that every proposed knob was implemented |
| S2 interactions | 128 factorial configurations plus [parser/layout regimes](encoded-cost-report.md) and [preset × token limit × emission](mixed-block-report.md), matched contexts and raw paired rounds | Bounded interaction studies complete; no exhaustive optimum claim |
| S3 optimizer comparison | [Bayesian report](bayesian-search-report.md): fresh three-seed random/NSGA-II/MOTPE, 10692 verified paired rows, equal unique and observed wall-time budgets, censored time-to-frontier | Bounded comparison complete; [frozen S9](final-tuning-report.md) rejects speed/compromise worst-file growth and insufficient size-role gain |
| S4 GPU crossover | [Trained fitting/scoring](trained-surrogate-report.md) plus actual [whole-loop accounting](bayesian-search-report.md); CPU fallback at 880 candidates | Bounded spike rejected: fit parity failed, latent prediction/calibration failed, optimizer-replacement upside at most 0.15%; no unsupported GPU search speedup |
| S5 context policy | [Native policy report](context-policy-report.md): 663 paired rows, nested grouped CV, native selection cost, sampling traps and parity gates; [S9](final-tuning-report.md) measures every frozen policy | Size tree passes final internal guards: 0.56% smaller and 1.31× faster than Best on the fixed mixed set; retain an opt-in research profile, dominated by miniz6 in aggregate |
| S6 latent representation | [Trained surrogate report](trained-surrogate-report.md): 10659 unique labels; trees versus explicit/latent ensembles, source/family and config holdout, group calibration, raw predictions/checkpoints | Bounded spike rejected: trees predict/rank better, intervals too wide, no reduced encoder evaluations; retain CPU baseline for S3 whole-loop study |
| S7 encoded-cost parsing | [Exact oracle and native bounded DP](encoded-cost-report.md): 128 native/Python witnesses, exhaustive binary inputs through eight bytes, 1456 paired rows and three decoders | Bounded spike complete and rejected for production Best: high CPU cost and worst-file guard failures; frozen roles retain Balanced/Best |
| S8 mixed-block emission | [Eight-offset native DP](mixed-block-report.md): 2184 paired rows, 21 methods, matched compressed-only controls; exhaustive type sequences, all-offset stored packets and three decoders; Lean scope reviewed | Bounded spike rejected for production replacement; no general improvement over Balanced/Best, mixed append outside current encoder theorem |
| S9 validation/portability | [Final report](final-tuning-report.md): 11 methods, 44 reserved/19 tiny inputs, ten rotated sessions, 6930 paired rows, 99 RSS runs, 22 linked builds, direct miniz1/6/9, framing and [439 Lean/Rust packet checks](../scripts/reports/search-final-correspondence.json) | Final bounded validation complete; preserve the 3015-row schedule-error attempt separately, never use it for final claims; claims cover M5 only, Linux CI is correctness evidence |
| Synthetic extensions | Original families, S5 Zipf/Markov/template edits; [new cost, three collision, change/drift, sampling-trap and paired-transform families](encoded-cost-report.md), 27 train/18 validation/18 reserved cases; native repeated wraps and arithmetic 4GiB-boundary simulation | Generator spike complete; the arithmetic simulation is not a native 4GiB encode or a 32-bit Rust proof |
| Publication and verification | S5 CI 37580753441, S6 CI 37582002781, S3 CI 37583954135, S7 CI 37587352164 and S8 CI 37588707263 succeeded; S9 data/guard reconstruction and mandatory native/model gates added | All evidence and negative results exported; final publication must pass the [CI workflow](../.github/workflows/ci.yml) before the goal is marked complete |

The reserved cases were first encoded only after freezing S9 candidates and
thresholds. A scheduling error aborted the initial attempt; the corrected
series uses the same methods, policies and numerical criteria. The rejected
attempt is retained with source/binary hashes and no selection feedback.
Previously visible real holdout data remains regression evidence. No cloud
compute or performance claim for unmeasured hardware is part of the design.

## Final decisions

1. Keep the CPU random/NSGA-II/MOTPE tools. GPU/latent proposals have not shown
   a useful whole-loop benefit for this 880-configuration search.
2. Keep the exact oracle, compiled geometry, generators and mixed emitter as
   isolated research tools. Their native results do not justify default changes.
3. Retain the [measured size policy](../scripts/reports/final-size.policy) for
   opt-in experiments. The faster S3 points are real tradeoffs, but fail the
   predeclared worst-file guard; no universal reference victory is claimed.
4. Production defaults and Lean source remain unchanged. Tests establish finite
   Rust/model correspondence, not a Rust refinement or speed/quality theorem.

Final publication CI is required before marking the goal complete. Further
algorithms, production integration of research profiles and additional hardware
are follow-on work, not claimed achievements of this bounded investigation.
