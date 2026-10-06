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

Rust uses one-position lazy matching. Searching the next position needs
only a yes/no decision: a closer distance wins at equal length, and any
other distance needs one extra byte. Lean `better_match_iff_threshold`,
built on `accept_prefix`, proves that checking this threshold prefix is
equivalent to the existence of an accepted better match at that distance.
Rust checks those prefixes across the same bounded hash chain and stops at
the first success. A maximal distance-one match cannot be improved.

The current search also rejects older candidates that disagree at the
first byte beyond the best match, and compares long runs in eight-byte
chunks with explicit little-endian conversion. The original byte-by-byte
search remains a test reference: token sequences must agree on seeded
inputs, short tails, repeated patterns, overlapping matches, and window
wrap. This is finite evidence for the Rust implementation, while Lean
proves the threshold rule and correctness for every checked finder.

Long advances insert hash entries through bounded three-byte windows,
checking the input and stored-position limits once per run. Short advances
keep the scalar path: bulk setup regressed text in the candidate measurement.
`bulk_insertion_preserves_scalar_tables` compares all heads, links, and the
cursor against the original inserter, including ring wrap and short tails.
