# S1 geometry and S7: encoded-cost parsing

The short exact oracle improves fixed-code bits in 108/128 constructed cases
and whole bytes in 77/128. Every native exact bit count matches
the independent Python oracle, and every output passes deflate-core,
miniz_oxide and exact-consumption zlib. An additional exhaustive forward
parse enumeration covers all binary inputs through eight bytes.

The oracle solves a position DAG containing every legal literal/match
edge, with literal 8/9-bit costs, length/distance codes and extra bits,
three header bits, seven EOB bits and final byte padding.
[RFC 1951](https://www.rfc-editor.org/rfc/rfc1951.html)
This optimality is for one fixed-code block. It does not cover dynamic
Huffman costs, other candidate graphs or block splitting.

## Bounded native prototype and geometry

The native prototype inserts all positions into a three-byte hash chain,
scans at most 4/16/64 candidates and parses raw chunks of 512/4096/16384
bytes. Greedy chooses the longest match; fixed-cost DP considers all legal
prefix lengths and their cheapest available distance. Nearer matches with
equal or longer prefixes dominate older fixed-cost candidates. Tests check
DP is no worse than greedy on the same graph and exercise repeated ring
wraps. Every emitted match is compared to input bytes with distances
bounded by the compiled history, never exceeding 32768.

Eight hash/history layouts are compiled into isolated source/compiler/flags
keyed builds. Hash widths 12–18 and histories 1–32 KiB are validated;
the experiment samples eight layouts. Default, small and large table
capacities are 512 KiB, 40 KiB and 2.25 MiB on this 64-bit machine.
These are research-parser tables, not changes to production Matcher.
Exact mode has no ignored external probe/layout fields; production preset
candidate identities mask inactive geometry fields.

Fixed mode emits a single fixed block. Auto mode reuses the checked
fixed/dynamic emitter with 16384-token splits and a whole-input stored
fallback. It does not implement S8 mixed stored blocks. Dynamic codes
are rebuilt from selected tokens, so fixed-cost DP can worsen actual
dynamic output. No optimality is claimed for auto emission.

Sixty training and 44 validation cases combine previous mixed workloads
with new cost-sensitive matches, three hash-collision generators, change
points/drift, sampling traps and paired transforms. Real files are capped
at 256 KiB with source ranges retained. Old validation is regression;
new synthetic regimes are separately identified. Fourteen canonical
methods/layouts are frozen before validation; roles use training only.
All predeclared methods/layouts remain validation sentinels. The 14 prior
synthetic and 18 extension tests remain unencoded; S5 final cases also
remain reserved. Five training/seven validation paired rounds use 5 ms
minimum batches. Timings include matching, parsing, allocation and emission.

## Native validation

| Method / geometry | Speed vs paired Balanced | Packed-size change | Maximum file-size ratio |
| --- | ---: | ---: | ---: |
| cost:64:16384:auto / hash 15 / history 32768 | 0.047× | -1.540% | 1.296× |
| cost:16:4096:auto / hash 13 / history 4096 | 0.079× | +4.003% | 1.640× |
| cost:16:4096:auto / hash 18 / history 32768 | 0.073× | -0.146% | 1.499× |
| best | 0.513× | -0.623% | 1.007× |
| cost:16:4096:auto / hash 15 / history 32768 | 0.073× | -0.122% | 1.499× |
| cost:16:4096:auto / hash 15 / history 1024 | 0.088× | +9.914% | 2.544× |
| cost:4:512:auto / hash 15 / history 32768 | 0.109× | +2.297% | 1.882× |
| cost:16:4096:auto / hash 12 / history 1024 | 0.087× | +9.919% | 2.553× |
| cost:16:4096:auto / hash 17 / history 16384 | 0.076× | +0.852% | 1.519× |
| longest:16:4096:fixed / hash 15 / history 32768 | 0.181× | +21.604% | 3.580× |
| cost:16:4096:fixed / hash 15 / history 32768 | 0.075× | +17.102% | 3.575× |
| balanced | 0.998× | +0.000% | 1.000× |
| cost:16:4096:auto / hash 18 / history 1024 | 0.087× | +9.914% | 2.544× |
| cost:16:4096:auto / hash 12 / history 32768 | 0.070× | -0.007% | 1.505× |

Scope aggregates and source/family/paired-round confidence intervals
are retained in the JSON. Table rows combine the mixed cases; the real,
old synthetic and extended synthetic scopes must also be inspected.

## Decision and verification boundary

The exact counterexamples validate the parsing hypothesis under fixed
codes. The bounded prototype does not belong in production Best: its
encoder cost is high and its worst-file growth exceeds the predeclared
20% guard. Training-selected speed/compromise stay Balanced and size
stays Best. Retain the negative prototype and geometry findings.

Existing Lean proofs cover the model’s checked finder and fixed/dynamic
emission policies. They are not a refinement proof of this Rust parser
or a theorem about encoded-size optimality. No Lean model or production
core source changes. Three-decoder/byte-count/enumeration gates provide
finite cross-implementation evidence. The 4GiB-boundary test shifts an
absolute-link arithmetic model by 2^32 with small rings; it allocates
no 4GiB input and does not establish native 32-bit portability.

[Full evidence](../scripts/reports/search-cost.json) retains exact raw inputs,
native packets/tokens, frozen roles, geometry/build provenance, case
construction witnesses and raw observations in the
[gzip ledger](../scripts/reports/search-cost-measurements.jsonl.gz) (1456 rows).

```sh
make research-cost-check
python3 scripts/search_extended_corpus.py --out target/search/EXTENSIONS
python3 scripts/search_cost_campaign.py --extensions target/search/EXTENSIONS --out target/search/cost/RUN
python3 scripts/search_cost_report.py --campaign target/search/cost/RUN
```
