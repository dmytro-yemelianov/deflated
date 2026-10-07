# P5 preparation: frozen role combinations

Status: preparation only. No new final-test encoding or feature extraction.
The [original contract](encoder_protocol.json) and all role guards stay fixed.

After the initial P4 budget, prepare three combinations with the independently
retained P2 code-reversal optimization. This is a bounded confirmation of
selected components, not another adaptive-grid search:

| Role | Combination | Known limitations before final testing |
| --- | --- | --- |
| Maximum speed | P2 reversal plus a short-Balanced policy with the original 1-probe greedy/tail-8 trigram leaf | Original large-input profile already fails old per-file size limits; retain as an explicit loose tradeoff, with no promotion claim. |
| Compromise | P2 reversal plus the P4 depth-one feature policy | P4 real validation is only 1.108× Balanced; the speed target remains unmet. The tree uses only legacy feature 10, so serialize the identical tree as v1 to avoid computing its two unused enhanced features. |
| Minimum size | P2 reversal plus the frozen original size policy | No new packet-size claim: it retains the original policy choices. A new frontier point requires a measured speed improvement under the same guards. |

Before opening the held test, compare assembled binaries on train/validation,
checking packet identity against their component encoders and scalar reversal
at clamped/wide bit widths. Record all changed build/source/policy hashes and
complete the actual portable CLI size check. No mixed stored emitter is in
these proposed combinations.

Freeze the source, binaries, all three policies, control methods, protocol and
both corpus manifests before any final-test encoding. Measure ten serial paired
warm/first-call sessions against the sealed original worker, retain all eleven
original controls including miniz1/6/9, and report real/synthetic/regression
scopes separately. Measure tiny latency and separate-process RSS, and check
new packets through the actual Lean/Rust decoders. Final-test results decide
the guards; missed targets and the known loose speed tradeoff must remain
visible. Any later tuning needs a new holdout or an explicit regression label.

The v1 serialization removes unused features without changing the selected
branch or leaf. Its lower overhead is a hypothesis until the assembled native
measurement. P6 integration and exact-revision CI remain required after P5.

The assembled validation pilot at commit `d977bb5` completed 93 paired rows
and 62 direct controls in 13.561 seconds. Every candidate packet also matches
the same policy executed by the sealed original worker (93 independent
component-identity checks). Internal Balanced packets remain identical too.
This is one warm session at a 5 ms minimum, without final confidence,
first-call, tiny or RSS conclusions.

| Role | Real validation speed / original Balanced | Real bytes / original Balanced | Largest real file ratio |
| --- | --- | --- | --- |
| Maximum speed | 2.175× | +7.593% | 1.299× |
| Compromise | 1.170× | +0.325% | 1.021× |
| Minimum size | 0.690× | -0.339% | 1.000× |

Speed violates the 20% file cap (and reaches 1.950× bytes on the old outlier
scope). The compromise speed target remains unmet. Size is 1.224× original
Best but +0.012% larger, missing the -0.2% size target. These are pre-final
warnings; the role guards will not be relaxed.

Evidence: [pilot summary](../scripts/reports/encoder-p5-combinations.json),
[pairs](../scripts/reports/encoder-p5-combinations-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p5-combinations-controls.jsonl.gz),
[diagnostics](../scripts/reports/encoder-p5-combinations-diagnostics.json.gz),
[component identities](../scripts/reports/encoder-p5-combinations-component-identity.json.gz).
The exact binary and source archive are sealed at the local pilot directory.
The final-test freeze is still pending. The [actual default portable CLI
size check](../scripts/reports/encoder-p5-portable-size.json) uses the same
Rust 1.88.0 compiler and default release flags for original archived source
and commit `d977bb5`: 542336 →542304 bytes (-32), passing the +64 KiB guard.
Policy payloads are separately 72/99/96 bytes and remain research-worker
inputs. This size result covers the portable core optimization and default
CLI; a future release CLI exposing new presets must be measured separately.
