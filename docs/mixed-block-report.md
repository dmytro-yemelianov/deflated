# S8: alignment-aware stored/fixed/dynamic blocks

The prototype finds the minimum final padded bit count for an existing
token partition and its checked per-block Huffman lengths. Its eight
states track the current bit offset. Fixed/dynamic transitions include
headers and EOB; stored transitions include the three header bits,
alignment, LEN/NLEN, payload and additional 65535-byte segments.
Final byte padding participates in the recurrence. Blocks share one
writer; exactly the last segment is final, and matches may reference
bytes previously emitted by stored blocks.

This is not a globally optimal splitter or Huffman-code optimizer.
The outside whole-input stored option applies to both mixed and
compressed-only controls without allocating a discarded stream.

## Native experiment

Three presets × three token limits (1024/4096/16384) × mixed versus
compressed-only emission plus three unchanged presets give 21 methods.
Five training/seven validation paired rounds (5 ms minimum batches)
cover the S7 60/44 mixed cases. All methods are frozen validation
sentinels; role selection uses training only. Real validation is
previously visible 256 KiB chunks, and 32 reserved cases stay unencoded.
Timing includes token collection, frequency/code construction, planning,
emission and the prototype’s evidence allocations.

| Native validation method | Speed vs paired Balanced | Packed-size change | Maximum file ratio |
| --- | ---: | ---: | ---: |
| compressed:fast:1024 | 0.974× | +7.149% | 1.819× |
| compressed:fast:4096 | 1.210× | +5.126% | 1.801× |
| compressed:fast:16384 | 1.313× | +4.798% | 1.797× |
| compressed:balanced:1024 | 0.706× | +2.514% | 1.057× |
| compressed:balanced:4096 | 0.827× | +0.383% | 1.011× |
| compressed:balanced:16384 | 0.866× | +0.000% | 1.000× |
| compressed:best:1024 | 0.457× | +2.022% | 1.057× |
| compressed:best:4096 | 0.517× | -0.089% | 1.010× |
| compressed:best:16384 | 0.529× | -0.462% | 1.009× |
| mixed:fast:1024 | 0.979× | +6.395% | 1.819× |
| mixed:fast:4096 | 1.216× | +4.966% | 1.801× |
| mixed:fast:16384 | 1.318× | +4.769% | 1.797× |
| mixed:balanced:1024 | 0.714× | +1.761% | 1.057× |
| mixed:balanced:4096 | 0.827× | +0.224% | 1.011× |
| mixed:balanced:16384 | 0.857× | -0.028% | 1.000× |
| mixed:best:1024 | 0.461× | +1.269% | 1.057× |
| mixed:best:4096 | 0.501× | -0.248% | 1.010× |
| mixed:best:16384 | 0.516× | -0.490% | 1.009× |
| fast | 1.577× | +4.798% | 1.797× |
| balanced | 1.022× | +0.000% | 1.000× |
| best | 0.531× | -0.623% | 1.007× |

## Matched mixed versus compressed-only byte counts

| Preset / token limit | Mixed-size change from matched no-stored control |
| --- | ---: |
| fast / 1024 | -0.7040% |
| fast / 4096 | -0.1518% |
| fast / 16384 | -0.0268% |
| balanced / 1024 | -0.7346% |
| balanced / 4096 | -0.1588% |
| balanced / 16384 | -0.0281% |
| best / 1024 | -0.7381% |
| best / 4096 | -0.1594% |
| best / 16384 | -0.0282% |

Mixed emission cannot increase size against its matched control with
the same token partition. It still loses the training-selected overall
tradeoff to unchanged presets: speed/compromise select Balanced; size
selects Best. Retain the mechanism and negative production decision.

## Correctness and model scope

Every measured candidate and paired baseline passes deflate-core,
miniz_oxide and exact-consumption zlib. Native tests compare the DP
against every type sequence for up to seven blocks at all eight offsets.
Actual stored append packets cover every offset and payload lengths
0/65535/65536/131071; mixed packets exercise backreferences across
block histories, and emitted bits equal the predicted costs.

`spec/Deflate/EncodeSplit.lean:emitSplitBlocksGo` calls `emitBlock`
for fixed/dynamic blocks. `compressSplit` and `Compress.compress`
choose stored only for the entire input. Those encoder theorems do
not cover this mixed stored append operation or selection recurrence.
Production promotion would need an append/alignment model and decoder
loop invariant for arbitrary prior output. No production or Lean source
changes are made; format tests are finite evidence, not a Rust proof.

[Report](../scripts/reports/search-mixed.json) and [raw ledger](../scripts/reports/search-mixed-measurements.jsonl.gz) retain 2184 paired rows,
native packet witnesses, source/build hashes, frozen roles and scopes.

```sh
make research-mixed-check
python3 scripts/search_mixed_campaign.py --out target/search/mixed/RUN
python3 scripts/search_mixed_report.py --campaign target/search/mixed/RUN
```
