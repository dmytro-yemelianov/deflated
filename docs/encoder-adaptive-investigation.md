# P4: regional effort and block decisions

Status: initial regional/predictor training screen complete; corrected
predictor, streaming blocks and learned policies remain separate P4 work.
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
