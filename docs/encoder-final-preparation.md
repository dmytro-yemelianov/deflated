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
