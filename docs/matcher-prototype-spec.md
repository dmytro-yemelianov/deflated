# A: tagged/grouped matcher specification

Status: unimplemented research design v1; cancelled on 2026-10-07 when active
R&D ended. No matcher equivalence or performance result follows from this
specification. See the [closure report](new-methods-report.md).
The historical design was governed by [the plan](new-methods-plan.md) and
[protocol](../scripts/new_methods_protocol.json). No implementation speed claim.

## Domain, contracts and hypothesis

Retain raw RFC 1951 output, 32768-byte maximum distance, match lengths 3–258,
checked matches, lazy/pending semantics and current fixed/dynamic/stored emission.
The baseline matcher uses 15-bit hashes, absolute u32 heads, u16 predecessor
distances, bulk/periodic insertion and input-dependent single/dual indexing.
Read actual sources: graph snippets have stale line offsets in this checkout.

Hypothesis: cached exact prefix bytes and bounded group processing can reduce
candidate input loads or compare overhead. Added writes, allocations, gathering,
generation checks and footprint may erase the benefit. Counters and total encode
time decide; SIMD speedups are not assumed on stable Rust 1.88.0.

## A1: preserved candidate sets and order

Add cached exact 24-bit three-byte prefixes or guarded 32-bit four-byte prefixes.
These are rejection hints, not permission to accept a match. Each cached entry
has an owner position/generation; use only when it describes the exact candidate.
Missing/stale/unrepresentable metadata falls back to the original comparison.
Original head/link state remains authoritative.

- A three-byte chain may reject an unequal exact three-byte tag. It may reject
  an unequal fourth byte only when this query requires at least four bytes.
  A valid length-three candidate with a different fourth byte must survive.
- A four-byte chain requires length ≥4 and can use a four-byte prefix tag.
  Never reuse that rule in the trigram fallback or equal-length-three lookahead.
- Hash/fingerprint equality is insufficient: perform the original bounded full
  common-prefix/threshold comparison and `accept` checks for retained candidates.
  Lossy hash fingerprints may reject only on inequality of identical functions
  applied to the same required bytes; they are not in the initial exact-tag roster.
- Preserve newest-first order, strict better-length updates, closest-distance
  tie handling, probe accounting, `enough`/full-match early termination and all
  lazy thresholds. A rejected tag still consumes its original probe slot.
- Virtual pending candidates are checked from original bytes when not inserted.
  Preloading four candidates does not insert them, update best prematurely,
  consume extra semantic probes or reorder the winning tie.

Sidecar layout stores metadata separately from links. Interleaved layout stores
the unchanged link with metadata in a safe packed integer/ordinary struct.
Both retain an explicit owner guard. Batch widths 1/4 process lanes in original
order, recomputing thresholds after each winner; speculative loads are bounded
and timed. Bulk runs and periodic insertion must populate every cache entry
consistently or mark it invalid. Disabling their original optimization without
charging its lost benefit is forbidden.

Roster: tag none/24/guarded32 × sidecar/interleaved × batch1/batch4 =12. No-tag
variants quantify layout/gather overhead and serve as negative controls.
Configuration IDs encode all three axes and source hashes. Count allocations,
metadata bytes/writes, scalar fallbacks, candidates loaded/visited/rejected,
comparison bytes and lazy checks in a separate instrumented specialization.

## A2: contiguous bucket dictionary, changed coverage

Use 4096/8192 buckets ×4/8 recent slots ×trigram-only/dual-index =8 variants.
Each slot contains a checked absolute position and exact index-prefix tag.
Insert every original eligible position; replace the oldest slot deterministically.
Visit valid slots newest-first. Dual indexing searches four-byte candidates for
long matches, then the three-byte fallback under the specified original policy.
Use the baseline lazy threshold/acceptance rules, but do not claim identical
candidate coverage or packets. All history/window, owner and tail checks remain.

No whole-input retry, skipped-position insertion, learned predictor, extra index
size or arbitrary effort mode belongs to this roster. A future fallback or
adaptive bucket width consumes a documented additional budget. Fingerprint
tables and LZ dictionaries are established ideas; the proposed contribution is
the particular bounded layout and its measured interaction with this matcher.

## Required invariants and evidence

For both designs: indices/reads in bounds, only backward positions, distance
1–32768, matching bytes, advancing tokens, deterministic insertion/replacement
and no new integer truncation. Input beyond representable metadata positions
uses a safe scalar/no-candidate fallback, preserving losslessness; test simulated
near-u32-limit state without allocating multi-gigabyte fixtures.

A1 must match baseline heads/links/cursors/pending state, ordered candidates,
complete token lists and packets. Tests cover empty/tails, all hash/tag collisions,
3-byte/fourth-byte witnesses, distance one and full-window distance, multiple
wraps, runs/periodic phases including hash collisions, skipped insertion cases,
lazy ties and early stops. Test original Fast/Balanced/Best plus relevant old
configs on regression data; default/all-feature builds must agree.

A2 must expand every token to the original input and preserve `accept`; compare
actual sizes with Balanced/Best and all matched native controls. Existing
`decode_compress` applies to a checked finder in the Lean model. Rust/model
correspondence stays finite evidence; no performance or Rust refinement theorem
is claimed. No new emitter/model proof is needed for unchanged emission.

## Placement and acceptance

Start in a research-only implementation/example; ordinary core has no extra
dependencies, unsafe code or experimental branches on its default hot path.
Promotion may move an A1 implementation into the core after all equivalence,
primary speed, first-call, tiny, RSS, binary and exact-revision CI gates pass.
A2 needs the explicit coverage-role gates and same-guard frontier comparison;
any useful loose tradeoff remains opt-in and labelled.

Negative results terminate a configuration/family and are retained. At most two
training-selected A sentinels advance to validation and final confirmation.
Thresholds and role guards are in the common machine protocol; original b7
and the previously completed P0–P6 reports remain immutable historical controls.
