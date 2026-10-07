# P4: regional effort and block decisions

Status: the initial 24-recipe P4 investigation and independent validation
are complete. No recipe reaches its primary role target. P5 final protocol,
useful P2 combinations and P6 integration remain separate work.
Final-test inputs stay reserved and no new preset/default is promoted.

The initial 15-method screen consumes 15 of the declared 24 P4 recipe budget:

- 12 regional matchers: light budget 4/16 × stop length 4/8/16 × trigram/dual
  index. Ambiguous positions retain 128 probes. All positions are indexed;
  lazy matching is used only for current matches <=16 bytes. Both dictionary
  history and final match acceptance remain unchanged.
- Three tagged four-byte predictors (4096/16384/65536 sampled positions),
  followed by the regional 4/8/trigram matcher when repetition is detected.
  A jittered whole-input sample counts exact word reuse within 32 KiB and
  retains full tags to exclude hash-only collisions. Low reuse selects stored
  output. This is a heuristic: it cannot guarantee a size cap on unseen data.

Predictor allocations/sampling and every match/emission pass occur inside
`encode` and are fully charged. Short inputs skip the predictor. The separate
exact-comparison adapter always computes Balanced too and enforces a 1% or
20% per-input cap with integer arithmetic. It is not in the initial 15-method
roster: three corrected predictors, three policy/fallback profiles and three
streaming-block recipes complete the initial budget. Three unspent streaming
slots were reassigned to the correction after the measured false positives
below; the 24-recipe budget is unchanged. An always-computed original-equivalent
baseline cannot by itself produce a 1.5× speedup; its extra cost must be measured.

The adaptive type is behind `research-tuning`. Normal preset/config policies
retain the original decisions; tests compare full-effort adaptive output to
the original config and check accepted tokens, ring wraps and Rust/miniz
decoding for all 12 regional recipes. Predictor tests include uniform random,
periodic wraps and short inputs. Exact fallback compares actual packet sizes.
Native pilot pairs additionally check exact zlib consumption and identical
internal Balanced packets against the sealed original.

On the three S9 outliers, the original speed profile grows bytes 67.908%
aggregate (1.950× worst file), compromise grows 18.753% (1.456×), and old
speed policy grows 12.989% (1.207×). These exact sizes are preserved in the
[original control screen](../scripts/reports/encoder-baseline-train.json).
By construction, cheap configurations limit candidate coverage and some
also insert fewer match-interior positions; generic sampling can route an
ambiguous input to that cheaper search. This is a qualitative explanation
consistent with the packet-size regressions, not an independent attribution
of each matcher branch. Full-history dual regional search repairs the old
size caps below, while its real/synthetic costs show why that repair cannot
be enabled everywhere. The drift stored-prediction failure is a different,
explicitly reproduced issue: byte-alphabet compression missed by word reuse.

## Initial training result

The frozen initial implementation is commit `64e7cdd`. The serial screen
contains 465 paired candidate rows and 62 old-policy/miniz6 control rows,
covering eight real training sources, 20 new synthetic training cases and
three old outliers. All decoder and internal-Balanced identity checks passed.
The screen took 68.173 seconds; it is a one-session warm pilot, not a final
confidence, RSS, tiny-latency or integrated-size decision.

All 15 methods were slower than original Balanced on the real training
scope (0.796–0.910×). The highest real throughput used the 16384-sample
predictor: 0.910×, +1.519% aggregate bytes, 1.107× worst-file bytes. Regional
16/16/dual was 0.820× with +0.083% bytes. None meets the main target.
On the three old outliers, 16/16/dual was 2.910× Balanced and saved 6.084%
aggregate bytes, with a 1.034× worst-file ratio. That local benefit does not
offset failure on new real and synthetic workloads.

The cheap predictors incorrectly selected stored output on synthetic drift:
`drift-7` grew from 186938 to 262169 bytes and `drift-10` from 185037 to
262169 bytes. Low exact four-byte reuse missed compression available from
a small byte alphabet. The corrected predictor additionally requires at
least 240 sampled byte symbols and a peak frequency no greater than 2%.
This remains a heuristic, with all histogram work charged inside encoding;
the correction is evaluated as three new recipes, not relabelled old results.

Evidence: [summary](../scripts/reports/encoder-p4-initial.json),
[paired ledger](../scripts/reports/encoder-p4-initial-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p4-initial-controls.jsonl.gz) and
[diagnostics](../scripts/reports/encoder-p4-initial-diagnostics.json.gz).
The exact initial binary and source archive are sealed alongside the local
run at `target/encoder-performance/p4-train-v1`.

The three corrected recipes at commit `1606258` passed 93 native pairs and
62 controls (17.155 seconds). They remove both drift stored false positives:
synthetic aggregate growth falls to 1.241%, although the regional matcher
still causes a 1.361× worst-file ratio. Real speed is 0.907–0.946× Balanced
with +1.519% bytes, so all three remain rejected as standalone candidates.
Evidence: [summary](../scripts/reports/encoder-p4-entropy.json),
[pairs](../scripts/reports/encoder-p4-entropy-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p4-entropy-controls.jsonl.gz),
[diagnostics](../scripts/reports/encoder-p4-entropy-diagnostics.json.gz).

## Streaming prototype

The next three recipes share one Best token iterator and a 16384-token
buffer plus a single peeked token. First compare fixed/dynamic selection
without Best's separate quarter-split heuristic, then permit stored at the
identical partition, then permit regime boundaries after at least 256 tokens.
Two consecutive 64-token windows must agree on a changed long-match regime;
at most 128 tokens are retained. Frequencies are updated as tokens arrive,
with retained-tail frequencies subtracted before one Huffman analysis.
There is no full-input token collection or timed evidence list.

Stored costs include starting bit offset, padding, LEN/NLEN and 65535-byte
subblocks. Greedy choices are not globally optimal; the complete stream
still pays for the exact whole-input stored fallback. Diagnostic specializations
assert recomputed frequencies and actual bit costs. Tests cover all eight
append offsets, stored length boundaries, stored-to-compressed backreferences,
regime boundaries, default-partition packet equivalence and instrumentation
identity. These are native tests, not new Lean theorems; promotion of mixed
emission still requires the model review described below.

The three streaming recipes at commit `58fa5fb` passed 93 paired rows and
62 controls in 19.115 seconds. On real training, identical partitions without
stored are 1.032× Best with +0.338% bytes; enabling stored changes this to
1.030× and +0.264%. Adaptive boundaries are 0.857× Best with +0.131% bytes.
The adaptive version saves 0.347% versus Best on the old outliers but remains
0.002% larger on new synthetic training. None meets the minimum-size role
on the primary real scope; the cheaper partition loses Best's size savings.
Evidence: [summary](../scripts/reports/encoder-p4-stream.json),
[pairs](../scripts/reports/encoder-p4-stream-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p4-stream-controls.jsonl.gz),
[diagnostics](../scripts/reports/encoder-p4-stream-diagnostics.json.gz).
Before fitting policies, confirm three training-selected sentinels on
validation: corrected 4096-sample predictor (highest real training speed),
regional 16/16/dual (old-outlier size benefit), and adaptive streaming
(smallest new real training packet among streaming recipes). This is a
confirmation screen, not an expansion or restart of the 24-recipe budget.

At commit `3bdca61`, the confirmation screen completed 279 pairs (three
sessions) and 186 direct controls in 42.354 seconds. Corrected sampling
reaches 1.262× Balanced on real validation, but increases real bytes 2.152%
and has a 1.247× synthetic worst-file ratio. Regional 16/16/dual is 0.849×
Balanced with +0.025% real bytes and a 1.319× synthetic worst-file ratio.
Adaptive streaming is 1.054× Best with +0.271% real bytes; it saves 0.014%
on synthetic validation and 0.347% on old outliers. All fail their primary
role target. No final-test inputs were encoded.
Evidence: [summary](../scripts/reports/encoder-p4-sentinels.json),
[pairs](../scripts/reports/encoder-p4-sentinels-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p4-sentinels-controls.jsonl.gz),
[diagnostics](../scripts/reports/encoder-p4-sentinels-diagnostics.json.gz).

## Frozen selector experiment

The remaining three recipes compare the same training-fitted policy in
feature-only, regional-replacement and exact-1%-fallback execution modes.
The fixed leaf vocabulary is original Balanced, 16-probe lazy trigram,
original Best and stored. Depths -1/0/1/2 undergo three-fold nested CV.
Real source lineage and complete synthetic families, including both members
of paired transforms, stay in one fold. Real encode time is the first loss
component; total time breaks ties. Training leaves must satisfy 1% aggregate
size growth in every scope and 20% on every file. These are training
constraints, not generalization guarantees.

The v2 policy adds tagged-word repeat rate and the corrected stored hint to
the existing 13 features. Native/Python features are compared before fitting.
Feature computation and dictionary allocation occur inside every native
policy encode; original v1 policies keep their old features and behavior.
The regional mode replaces only the 16-probe leaf with 16/16/dual adaptive
effort; it performs no full-input retry. The exact mode runs the feature-only
candidate and Balanced, choosing by actual packet length with integer 1%
arithmetic. Tiny inputs take Balanced directly in all three modes.
Teacher leaf timings omit features and cannot establish a speed result;
the fully charged native policy screen and independent validation decide it.

At commit `43c6fa6`, 124 original-worker teacher measurements and native/
Python feature comparisons produced a depth-one tree: lag-256 equality count
<=217 selects Balanced, otherwise 16-probe lazy trigram. Both enhanced
features were available but neither appears in the selected tree. Nested
source-group CV is feasible but predicts only 1.019× real speed. Retain this
generalization warning instead of presenting the 1.196× inner-CV prediction
as an independent performance result. The current v2 runtime still computes
all 15 features; any feature pruning needs separate native measurement.

All 93 training pairs, 62 controls and 93 native/Python policy-choice checks
pass; three-session validation adds 279 pairs and 186 controls. The feature
policy gives 1.251× Balanced, +0.591% real bytes and 1.033× worst-file bytes
on training. On real validation it gives 1.108×, +0.325% and 1.021×; synthetic
and old-regression packets equal Balanced. It repairs the observed old
size-cap failures, but misses the 1.5× main speed target.

Regional replacement is 0.957× Balanced with +0.013% real validation bytes;
the larger effort does not justify its cost here. Exact baseline comparison
is 0.529× with +0.059% real bytes, respecting the integer per-input 1% cap.
Its two complete passes confirm the speed cost of an unconditional guard.
No size savings versus Best or superiority over native miniz is claimed.

Evidence: [teacher and nested CV](../scripts/reports/encoder-p4-selector-teacher.json),
[training](../scripts/reports/encoder-p4-selector-train.json),
[validation](../scripts/reports/encoder-p4-selector-validation.json),
[frozen policy](../scripts/reports/encoder-p4-selector-teacher.policy).
Each summary has paired/control/diagnostic compressed ledgers beside it;
the teacher also retains its complete matrix, protocol and policy-choice
checks. Exact binaries and commit archives are sealed in the local run
directories. The complete P4 screen has 744 training pairs (24 ×31),
558 confirmation pairs, 620 old-policy/miniz6 controls and 124 teacher rows.
All new final-test data remains unencoded.

An [export receipt](../scripts/reports/encoder-p4-receipts.json) records every
exported artifact's compressed and content hashes. The research CI checks
those receipts and all 93 preserved native policy-choice agreements.

## GPU and Lean decisions

Fresh whole-loop accounting for the selector records 7.079 seconds of
native measurement, feature comparison and decoder verification, and
0.151 seconds of CPU fitting (2.084% of their combined time). This is below
the preregistered 5% GPU reopening threshold even before adding the other
P4 native screens. Fitting, feature work and verification are all included
in that observed loop; no transfer or GPU speedup is assumed. Defer GPU
scoring and full GPU encoding: this investigation has not produced a new
GPU-suitable bottleneck or demonstrated a larger-batch end-to-end benefit.

The Lean review distinguishes accepted-token heuristics from new emission.
Existing finder/token and fixed/dynamic split models support experiments
with regional search; they are not Rust refinement proofs. `encodeStored`
and `decode_encodeStored` model a fresh byte-aligned stored stream. They do
not prove arbitrary-prefix stored append or its mixed-block history
invariant. Since all streaming recipes miss the primary size target, keep
them in the research example and do not promote mixed emission. A new
append/alignment model and corresponding roundtrip proof remain required
before any later promotion. P5 packet correspondence and P6 model/axiom
checks still apply; earlier green CI does not certify this new revision.

The initial screen uses all eight real training sources, 20 new synthetic
cases and the three old outliers. Original Best and separately timed Balanced
are paired; old size policy and miniz6 remain direct controls. Diagnostic
predictor counts and counterfactual regional sizes are collected outside
timing. All stages are serial; feature-only decisions require source-grouped
validation and include native feature cost before any role selection.

```sh
python3 scripts/encoder_adaptive_campaign.py --out target/encoder-performance/p4-train-NEW
```

Streaming work must compare the identical token partitions first, then
detected raw-regime changes, reusing frequencies and bounded token buffers.
Stored choice includes alignment, LEN/NLEN and any necessary 65535-byte
subblocks, without resetting dictionary history. Review the Lean append/
decoder invariant before promoting structural mixed emission.

P3 checkpoint CI at commit `03247b3` is green, including Rust, Lean/axiom,
differential/framing, published correspondence and fuzz. [CI evidence](https://github.com/dmytro-yemelianov/deflated/actions/runs/37610463245)
That result predates this new adaptive code; final revision checks remain due.
