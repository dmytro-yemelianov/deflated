# Malformed Streams Corpus

This directory holds curated malformed and hostile DEFLATE streams, minimized regression cases discovered through fuzzing, and boundary edge cases.

## Principles

1. **Deterministic Error Handling (Spec §10, §12)**:
   Every malformed stream must return a deterministic `Error` variant, never panic, never loop infinitely, and never silently output corrupt data.

2. **Zip Bomb and Hostile Input Defense (Spec §11)**:
   Hostile streams (e.g. decompression bombs) attempting to expand into gigabytes must be rejected immediately during streaming without allocating past caller-specified limits (`inflate_with_limit`).

3. **Regression Isolation**:
   Any disagreement between reference oracles or minimized fuzz findings must be added here as a permanent regression test.
