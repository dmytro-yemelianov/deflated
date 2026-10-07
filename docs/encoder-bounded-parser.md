# P3: bounded encoded-cost parsing

Status: 24-method training screen, three selected validation sentinels and
RSS checks complete. None qualifies for integration under the declared guards.
This code is confined to the research worker, with no production-core change.

The preregistered roster contains 24 methods: probes 4/8/16 × lookahead 0/1 ×
longest, fixed costs, preceding-block Huffman feedback, or feedback with one
refinement pass. Longest/one-step lazy serve as controls on the same dictionary.
Short lazy queries are limited to current matches below 32 bytes. Each query
visits at most its probe budget, including a virtual pending-literal link.
Cost modes consider at most probes+1 prefixes of each accepted candidate.
There is no whole-input candidate DAG, beam or full-position DP.

The parser uses the production trigram hash and 32 KiB history, compact
position/distance links, word comparisons and full accepted-match checks.
Fixed costs include literal, length/distance codes and extra bits. Feedback
starts with fixed costs, then uses the preceding committed block's actual
lengths; absent symbols are conservatively estimated at 15 bits. These are
heuristic costs, not guaranteed predictions of the next block.

The emitter buffers at most 16384 tokens per original block and one refinement
buffer, preserving raw boundaries/history. It computes frequencies once per
candidate, validates Huffman lengths and reuses the resulting table for emission.
Refinement tests a bounded literal tail/shortened match and accepts only a
strictly smaller **rebuilt** fixed/dynamic bit count including the header.
Feedback can change the next parse, so this local comparison does not guarantee
a global size improvement over the separate no-refinement method. Whole-input
stored fallback remains fully charged.

Diagnostics record candidate visits, examined comparison bytes, insertions,
lookahead queries, rejection, tokens/blocks, Huffman analyses/refinement choices,
estimated versus actual payload bits, headers/EOB and stored selection. A
constant generic removes these counters from timed calls. Allocation/RSS and
first-call guards remain separate measurements, not inferred from counters.

Local tests cover checked token expansion, tails, periodic/random ring wraps,
instrumented/uninstrumented packet identity, two native decoders and exact
emission-bit accounting. A separate one-block test compares actual padded
packet sizes with/without refinement; CLI validation rejects unbounded settings.
The campaign reuses all 128 S7 fixed-code witnesses, checks the independent
Python oracle, token expansion/costs and exact-consumption zlib decoding.
Bounded parses may miss that oracle's optimum.

All 24 methods were screened on eight new real training sources, 20 new
synthetic cases and three old S9 outliers. The sealed original Best is paired
serially, with its separately timed original Balanced as the speed headline;
old size policy and miniz6 controls use the same inputs. Real, synthetic and
regression results remain separate. Final-test files are inaccessible to this
driver. Selection used training only: the fastest method, the smallest output,
and its no-refinement counterpart were confirmed on the disjoint validation
split with three paired sessions. Final-test inputs remain unencoded.

## Native results and decision

The training screen has one session (744 paired rows plus 62 controls); the
validation has three (279 paired rows plus 186 controls). These are pilot
timings, with no final confidence or first-call claims. Every warm packet
passes Rust, miniz and exact-consumption zlib; internal Balanced packets also
match the sealed original across the worker changes.

| Method | Real-training speed vs original Balanced | Real-validation speed | Validation bytes vs Best | Validation worst file vs Best |
| --- | ---: | ---: | ---: | ---: |
| Longest, 4 probes, greedy | 1.452× | 1.439× | +3.874% | 1.129× |
| Feedback, 16 probes, short lazy | 0.558× | 0.625× | +0.706% | 1.031× |
| Feedback + one refinement pass | 0.533× | 0.588× | +0.704% | 1.031× |

The feedback/refinement method gives the smallest aggregate real-training
output among all 24 new recipes, but is still +0.988% versus Best. On real
validation, its +0.704% fails the size target of at least 0.2% reduction.
Refinement saves only about 0.002 percentage points on validation and slows
encoding. The fast method misses 1.5× and the main compromise's 1% size guard.

Secondary scopes prevent promoting the fast method with only P2 reversal:
it grows synthetic-validation bytes by 1.200%, but the worst file is 1.395×
Balanced. Old outliers grow by 27.476% overall and 41.573% on the worst file.
Feedback's old-outlier output is +31.585% versus Best, with a worst-file ratio
of 1.546×. The collision witnesses show why a uniformly small search budget
is insufficient; no correctness failure is involved.

Direct original controls on the same real validation inputs give miniz6
1.294× Balanced for +0.588% bytes, and the old size policy 0.688× for -0.339%.
The bounded size recipes do not beat these or original Best. All controls,
synthetic/family and per-file observations remain in the ledgers.

Seven training diagnostic cases for the 16-probe refined method account for
7,149,848 visits and 1,119,912 committed tokens; only four blocks retain a
refinement. Its estimated payload total is +4.573% above the rebuilt actual
payload. This is a workload-specific aggregate, not a prediction guarantee.
Header/EOB totals plus rebuilt payload bits equal the emitted stream bits.
Across 3072 training short-witness/method pairs, 585 reach the exact fixed-code
optimum and the worst gap is 132 bits. No bounded result falls below that
oracle. Tokens and both fixed/auto packets are preserved for every pair.

RSS uses five large training cases (LLVM, Chinook, zlib archive, an actual-hash
collision and random islands), three repeats for three selected methods and
four original controls: 105 fresh processes. The maximum median RSS deltas
versus original Best are -360448, -409600 and -344064 bytes respectively.
Memory is within the guard on these cases; output and runtime prevent promotion.
Memory packets match their three-decoder timing goldens and exact zlib decoding.

Decision: retain the prototype, diagnostics and negative results; keep Best
and the old size policy as controls. Do not combine these rejected size recipes
with P2 or alter defaults. Next investigate regional search effort and streaming
block decisions in P4. A wider cost search or new learned representation needs
new evidence and an explicitly bounded extension of this completed 24-method
screen; the current results do not justify an unrestricted cross-product.

[Training metadata](../scripts/reports/encoder-p3-train.json),
[training paired ledger](../scripts/reports/encoder-p3-train-measurements.jsonl.gz),
[native references](../scripts/reports/encoder-p3-train-controls.jsonl.gz),
[oracle witnesses](../scripts/reports/encoder-p3-train-oracle.json.gz), and
[cost diagnostics](../scripts/reports/encoder-p3-train-diagnostics.json.gz)
preserve the complete screen. [Validation metadata](../scripts/reports/encoder-p3-validation.json),
[paired observations](../scripts/reports/encoder-p3-validation-measurements.jsonl.gz),
[controls](../scripts/reports/encoder-p3-validation-controls.jsonl.gz),
[oracle packets](../scripts/reports/encoder-p3-validation-oracle.json.gz),
[diagnostics](../scripts/reports/encoder-p3-validation-diagnostics.json.gz), and
[RSS evidence](../scripts/reports/encoder-p3-rss.json) retain the confirmations.
Sources are frozen at commit `a4971aa`, with exact file/compiler/binary hashes
in each protocol. All native timing/resource stages ran serially.

```sh
make research-final-check
python3 scripts/test_encoder_parse.py
python3 scripts/encoder_parse_campaign.py --rounds 1 --out target/encoder-performance/p3-train-NEW
python3 scripts/encoder_parse_campaign.py --rounds 3 --partition validation --methods bounded:4:0:longest:0 bounded:16:1:feedback:0 bounded:16:1:feedback:1 --out target/encoder-performance/p3-validation-NEW
python3 scripts/encoder_parse_rss.py --study target/encoder-performance/p3-train-NEW --out target/encoder-performance/p3-rss-NEW
```

The worker builds under the original compiler/flags, hashes sources, binary,
corpora and its protocol before encoding, preserves diagnostic packets/tokens
and failures, and rejects source changes during timing. Lean's checked-token
and fixed/dynamic model contracts remain applicable; these tests do not prove
Rust refinement or performance. Actual native/Lean packets remain P5 work.
