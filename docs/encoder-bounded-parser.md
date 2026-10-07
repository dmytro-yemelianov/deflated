# P3: bounded encoded-cost parsing

Status: prototype and local verification complete; native training campaign
pending. No performance or compression improvement is established yet.
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

All 24 methods are screened on eight new real training sources, 20 new
synthetic cases and three old S9 outliers. The sealed original Best is paired
serially, with its separately timed original Balanced as the speed headline;
old size policy and miniz6 controls use the same inputs. Real, synthetic and
regression results remain separate. Final-test files are inaccessible to this
driver. Selection is training-only; validation and final guards are still due.

```sh
make research-final-check
python3 scripts/test_encoder_parse.py
python3 scripts/encoder_parse_campaign.py --rounds 1 --out target/encoder-performance/p3-train-NEW
```

The worker builds under the original compiler/flags, hashes sources, binary,
corpora and its protocol before encoding, preserves diagnostic packets/tokens
and failures, and rejects source changes during timing. Lean's checked-token
and fixed/dynamic model contracts remain applicable; these tests do not prove
Rust refinement or performance. Actual native/Lean packets remain P5 work.
