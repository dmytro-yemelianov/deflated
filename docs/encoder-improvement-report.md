# Encoder improvement investigation: final results

The bounded P0–P6 investigation is complete. The default encoder retains a
portable code-reversal improvement: **1.032× warm and 1.038× first-call speed**
on the eight independent real test inputs, with identical compressed packets.
All supplementary default guards pass. The main **1.5×/+1% compromise target
is not achieved**, and none of the three new role profiles qualifies for
release promotion. Rejected prototypes remain research-only.

## Final independent measurement

Source was frozen at `6c1cd1f4f8d69df79fd39609ab17ee82bceb385e`; the freeze
was published in `34febbcb61d72121ceeab5706d2b1e9e266ece3f` before the first
held encoding or feature extraction. The original is
`14f15e63e1a8955c5cfebf869ce065f29dd950fc`. Both builds use Rust 1.88.0
and the same default release flags on Apple M5/macOS 27.2.

Ten serial sessions cover 58 inputs ×15 methods = **8700 paired observations**,
plus **513 separate RSS processes**. Primary evidence is eight new real source
groups; 20 disjoint synthetic cases, three old outliers and 27 deduplicated
shared tiny cases are reported separately. Twenty-four real source groups
cover six classes in each train/validation/test split. The native campaign
completed in 787.9 seconds without failures or retries.

Warm batches last at least 20 ms (2 ms tiny). First-call measurements use
fresh processes and resident input, excluding startup and input I/O. Every
allocation, selector feature, policy decision, fallback and emission pass is
charged; decoding/oracle validation is outside the encoder timer. Candidate,
file and pair order rotate. Bootstrap bounds resample complete sessions
10,000 times and describe measurement noise, not population generalization.

| Candidate | Role baseline | Warm speed, summed medians | First-call speed | Packed-size change | Largest real file ratio | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Maximum speed | Original Balanced | 2.158× | 2.130× | +6.235% | 1.384× | Reject: size and decode caps |
| Compromise | Original Balanced | 1.161× | 1.176× | +0.389% | 1.030× | Reject: speed below 1.5× |
| Minimum size | Original Best | 1.317× | 1.326× | +0.344% | 1.010× | Reject: no required size saving |
| Default code reversal | Original default Balanced | 1.032× | 1.038× | 0.000% | 1.000× | Retain: all supplementary guards pass |

Session-bootstrap 95% speed intervals remain distinct from the median ratios:

| Candidate | Warm interval | First-call interval |
| --- | ---: | ---: |
| speed | 2.050–2.181× | 2.133–2.158× |
| compromise | 1.069–1.181× | 1.167–1.189× |
| size | 1.268–1.336× | 1.285–1.326× |
| default | 1.028–1.039× | 1.024–1.040× |

The compromise meets aggregate/per-file size, decode, tiny, RSS and binary
limits in every required scope, but misses both speed bounds. Its synthetic
and old-regression packets equal Balanced. Speed grows old-regression bytes
67.908%; its worst old file is 1.950× and worst new synthetic file 1.857×.
The minimum-size profile is +0.344% versus Best on real inputs, +0.157%
on synthetic and +4.866% on old regressions, instead of the required -0.2%.
All eleven original controls are retained. No profile qualifies under any
complete same-role contract, so no new qualifying frontier point is claimed.

## Direct native references

Direct raw-DEFLATE references are preregistered `miniz_oxide` 0.8.9 levels
1/6/9 on the same cases/sessions. These are the compromise comparisons:

| Reference | Compromise speed / reference | Compromise bytes / reference |
| --- | ---: | ---: |
| miniz1 | 0.160× | 0.915998× |
| miniz6 | 0.872× | 0.997674× |
| miniz9 | 1.534× | 0.998625× |
| best | 2.243× | 1.010193× |
| policy-size | 1.739× | 1.006731× |
| policy-speed | 0.924× | 0.998450× |

The compromise has 12.8% lower throughput than miniz6 while producing 0.233%
fewer bytes. It is faster than miniz9 on this workload. This does not establish
superiority over other implementations, machines or unmeasured levels.

## Real-file and family regressions

| Held real file | Compromise speed / Balanced | Compromise bytes / Balanced | Speed-profile bytes / Balanced | Size-profile bytes / Best | Default speed / old default |
| --- | ---: | ---: | ---: | ---: | ---: |
| cldr | 1.021× | 1.000000× | 1.274355× | 1.000000× | 1.040× |
| ecma262 | 1.352× | 1.029831× | 1.383786× | 1.000000× | 1.026× |
| liberation | 1.418× | 1.008046× | 1.093308× | 1.000000× | 1.087× |
| linux | 1.020× | 1.000000× | 1.285771× | 1.000000× | 1.047× |
| nyc-tlc | 1.026× | 1.000000× | 1.006283× | 1.009950× | 1.036× |
| openssl | 1.441× | 1.025758× | 1.289874× | 1.000000× | 1.035× |
| ripgrep | 1.654× | 1.016797× | 1.147409× | 1.000000× | 1.023× |
| xz-archive | 0.995× | 1.000000× | 1.000000× | 1.000000× | 0.999× |

ECMA-262 causes the speed profile’s 38.4% real-file growth; the synthetic
sampling trap causes 85.7%. Low fixed effort misses valuable matches on
collisions/traps. The size profile’s old collision case is 9.42% larger and
only 0.225× Best speed. Default reversal has small noisy slowdowns in some
synthetic/old families; it is not a universal speedup. The
[complete statistics](../scripts/reports/encoder-p5-statistics.json.gz)
preserve every method, role guard, direct comparison, family and file.

## Integration and resource limits

The accepted `u32::reverse_bits` implementation preserves zero/clamped widths
and bit offsets. Scalar correspondence tests cover all 16-bit words/widths
and wide/random/clamped 32-bit codes at all eight offsets. Default-vs-original
packet hashes agree on all 58 final cases; default builds use the same small
harness without `research-tuning`. No search-coverage or emitter change is
promoted, and no new release preset API is added.

Worst tiny median ratios are 1.050/1.040/1.035 for speed/compromise/size.
Maximum per-case median RSS increases are 0/49152/98304 bytes; default
reversal increases at most 163840 bytes. All are within the respective
1.20× and 8 MiB caps. RSS covers one largest case per real class, largest
synthetic, drift and the old collision case with three replicates per side.
The actual integrated portable CLI is byte-identical to its sealed P5 build:
542336 →542304 bytes (-32), within +64 KiB. Policies remain separate
research inputs (72/99/96 bytes), not release CLI features.

## Investigation outcomes and verification

[P1 profiling](encoder-profile-report.md) attributes about 79% of original
Balanced encode time to matching and 11% to bit writing. miniz6’s measured
cost distribution differs; shares alone do not explain the absolute ratio.
Tuning cheap search buys speed by reducing match coverage, and the measured
outliers show its size cost. Encoding both candidate and Balanced enforces
a measured per-input cap but makes the exact-fallback prototype only 0.529×
Balanced. A sampling predictor cannot provide a universal size bound.

[P2](encoder-speed-spikes.md) rejects iterator/acceptance/position rewrites
and retains reversal. [P3](encoder-bounded-parser.md) tests 24 bounded-cost
recipes; feedback/refinement costs more without beating Best.
[P4](encoder-adaptive-investigation.md) tests 24 regional/predictor/streaming/
selector recipes; grouped nested validation limits overfitting, but none
reaches its role target. These negative results close their bounded screens.
Unrestricted multidimensional tuning is not justified by them.

GPU fitting/proposal work is 0.151 of 7.229 seconds (2.084%) in the fresh
fully charged selector loop, below the frozen 5% reopening threshold.
Even removing all that work would reduce this loop by only about 2.1%.
No new GPU-suitable bottleneck or end-to-end benefit was established; GPU
scoring/full encoding and cloud spending remain deferred.

Lean 4.30.0, model build and standard-axiom gates pass. All **232 timed P5
packets** pass the actual Lean/Rust CLI decoders. Another **6144 P3 short
fixed/auto packets and 21 sealed P4 diagnostics** pass Lean/Rust/zlib, including
actual stored-to-compressed backreferences. These are finite tests. There is
no Rust refinement or performance proof. Mixed stored append/alignment and
cross-block roundtrip proofs remain required before future production
promotion; the rejected streaming prototype is not promoted.

Formatting, default/all-feature Clippy and Rust/research suites pass on the
frozen production sources. The published artifact audit reconstructs the
complete matrix, bootstrap statistics, references, RSS, guards and witness
hashes. CI runs these plus differential/framing, no-unsafe/no-std, model/
axiom gates and five existing bounded fuzz targets. Completion requires
a successful CI run on this report’s exact final revision; the final task
completion links that immutable run. The preceding frozen-source CI is
[34febbc](https://github.com/dmytro-yemelianov/deflated/actions/runs/37625157366).

## Evidence and reproduction

[Pre-test freeze](../scripts/reports/encoder-p5-freeze.json),
[case manifest](../scripts/reports/encoder-p5-manifest.json),
[export receipt](../scripts/reports/encoder-p5-final-receipt.json),
[complete raw paired ledger](../scripts/reports/encoder-p5-measurements.jsonl.gz),
[RSS](../scripts/reports/encoder-p5-rss.json.gz),
[P5 correspondence](../scripts/reports/encoder-p5-correspondence.json.gz),
[prototype correspondence](../scripts/reports/encoder-prototype-correspondence.json.gz)
and [actual integrated CLI](../scripts/reports/encoder-p6-integrated-size.json)
retain hashes/counts/decisions. Original and candidate archives/binaries are
sealed locally under `target/encoder-performance/`; committed revisions
and acquisition manifests permit rebuilding without relying on ignored files.

```sh
python3 scripts/test_encoder_final_artifacts.py
# Restore original-platform inputs/baseline/CLIs in an isolated checkout.
# This downloads source/license data when absent and validates frozen hashes;
# historical acquisition metadata and new reacquisition receipts stay distinct.
python3 scripts/encoder_final_restore.py
# The final revision retains all 76 measured-source hashes from 6c1cd1f.
# Reusing these inputs is regression reproduction, not another blind holdout.
python3 scripts/encoder_final_campaign.py prepare --out target/encoder-performance/p5-REPRO
python3 scripts/encoder_final_campaign.py measure --out target/encoder-performance/p5-REPRO
python3 scripts/encoder_final_stats.py --campaign target/encoder-performance/p5-REPRO
make all
python3 scripts/encoder_final_correspondence.py --campaign target/encoder-performance/p5-REPRO
```

The restore helper regenerates synthetic/old cases, checks original raw/license
hashes, reconstructs the historical archive when needed and builds the two
actual CLI references. Binary hashes require the original Apple M5 platform,
Rust 1.88.0 and flags; they are not cross-platform reproduction hashes.

Exact timings depend on machine/load; first-call is not cold OS/disk cache.
Only eight held real groups and capped/prefix inputs were tested. Repeated
synthetic/old/tiny data cannot establish broad workload generalization.
No held result was used to change candidates or thresholds.

## Next hypotheses

A future goal should focus on matcher work and memory access, preserving
accepted-token checks and measuring match coverage. With the original 79%
matcher share, reaching 1.5× by improving matching alone would require roughly
42% less matcher time under an unchanged-cost approximation. Candidate
fingerprints/cache organization and selectively charged local effort are
hypotheses, not demonstrated wins. Use a new independent holdout, bounded
variant budget and the same per-file limits before promoting another profile.
Further block/proof work or GPU batching needs new measured justification.
