# ADR 0006: The matcher checks every candidate

**Status:** accepted, implemented (Lean and Rust) · **Date:** 2026-10-06

## Context

The M7a encoder tokenizes input into literals and `(len, dist)` matches and
emits them as one fixed-Huffman block (or stored blocks when that is
smaller). Finding matches is the part with freedom in it: hash chains,
window sizes, lazy matching, SIMD comparison. None of that is what the
round-trip theorem should be about. A proof that depended on one particular
search would break the first time the search was tuned, and would put the
fiddly code (hash arithmetic, chain walking) inside the proof boundary.

## Decision

- The match search is an **untrusted finder**. In Lean it is a function
  `Finder` of the input and a position that returns a candidate
  `(len, dist)` or `none` (`spec/Deflate/Match.lean`).
- `compressTokens` **re-checks every candidate** with `accept` before
  using it: `3 <= len <= 258`, `1 <= dist <= 32768`, `dist <= i`,
  `i + len <= size`, and the `len` bytes at `i - dist` equal the `len` bytes
  at `i`. A candidate that fails the check becomes a literal.
- The theorems hold **for any finder**: `expand_compressTokens` (the tokens
  expand back to the input), `compressTokens_valid` (every match is legal),
  and, built on `decode_emitFixed` and `decode_encodeStored`, the headline
  `decode_compress`: `x.size <= limit -> decode (compress find x) limit = .ok x`
  for every `find` and every `x`. An adversarial finder costs compression
  ratio, never correctness.
- The Rust `matcher::accept` checks the same conditions as the Lean `accept`:
  Rust uses a slice comparison where Lean uses `(List.range len).all`. The Rust
  hash-chain matcher passes its best candidate through it before it becomes
  a `Token::Match`.

## Why the check is cheap

Scoring a candidate already means comparing `input[i..]` with
`input[i - dist..]` to find how long the match runs. `accept` repeats that
comparison once, for the single winning candidate per position, instead of
once per chain link. The cost is one extra bounded `memcmp` of at most 258
bytes per emitted match. The perf report (`docs/perf-report.md`,
Compression) is not a measurement of this check alone, and no claim is made
that it is free; it is claimed to be small next to the chain walk it follows.

## Alternatives considered

- **Prove the Lean finder correct.** A real search is a large proof about
  hashing and chain invariants, and any later improvement reopens it. The
  check gives the same guarantee with a few lines.
- **Trust the Rust finder, check only in tests.** Then the theorem would
  need a hypothesis about the finder that the Rust code never discharges.
- **No finder at all (literals only).** Provable, but not an encoder
  anyone wants.

## Consequences

- The Lean `DEFLATE` oracle command uses a finder that always returns
  `none`, so Lean emits literals. The Rust matcher finds real matches. The
  differential harness therefore cannot compare `DEFLATE` output byte for
  byte across the two. It checks instead that Rust, Lean and zlib each decode
  every produced stream to the input, and compares `EMIT` (explicit token
  lists) byte for byte, which exercises the shared emit path with matches.
- The Rust-to-Lean link for the encoder is **mirroring plus differential**:
  `accept`, `emit_fixed` and `deflate` mirror their Lean definitions, and
  tests and the harness check that. There is no refinement proof (ADR 0003).
- A better finder (lazy matching, longer chains, dynamic Huffman) is a
  Rust-only change plus a differential re-run; the Lean theorems stand.

## Matcher tuning

`CompressionLevel` chooses greedy Fast (four probes), lazy Balanced
(sixty-four probes, the default), or lazy Best (512 probes). The finder uses
four-byte hash chains for longer matches and falls back to a separate
trigram chain for length-three matches. Chain heads are absolute positions;
links are sixteen-bit backward distances. Balanced chooses a compact single
trigram index with 128 probes for sampled short periods. For flat byte samples
it retains the previous trigram matcher, which proved faster in the synthetic
regression check. Both retain match search and avoid the second index.
Sampling selects an arbitrary finder; it does not bypass compression. A distance of 32768 remains
representable and zero terminates the chain. A reference test compares
compact links with absolute predecessor chains across repeated window wrap.

Searching the next position needs only a yes/no decision: a closer distance
wins at equal length, and any other distance needs one extra byte. Lean
`better_match_iff_threshold`, built on `accept_prefix`, proves the threshold
rule for accepted matches. Four-byte-chain candidates also require at least
four bytes; equal-length-three lookahead uses the short chain. Rust stops
at the first qualifying prefix, with a maximal distance-one match as the
unimprovable case.

Older candidates that disagree beyond the best match are skipped, and
portable little-endian word loads compare long runs. A scalar full-length
search over each preset's candidate sets remains a test reference. Tests
compare complete token sequences and check every emitted match with
`accept`, including seeded inputs, short tails, overlaps and window wrap.
The presets deliberately change the old search coverage and token stream.

Balanced and Best insert every position. Uniform-byte runs and checked overlapping periodic matches fill predecessor
links in batches, preserving all heads, links and insertion cursors. Periodic
batching includes collisions between phases and leaves unchecked trailing
hash windows on the scalar path. Fast
indexes the start and final sixteen positions of long advances, accepting
less search coverage for speed. Best also uses the existing checked split
callback to compare encoded bit costs at quarter boundaries. The arbitrary
finder and checked-split Lean theorems continue to apply; ratio and speed
remain empirical properties measured in `docs/tuning-report.md`.
