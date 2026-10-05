# Verification boundary

What this document means by each claim, per spec §2. Read it before quoting
any correctness claim about this project.

## What is proved

Named theorems in `spec/Deflate/Properties.lean`, kernel-checked by Lean
4.30.0 with no `sorry`, no `admit` and no project-defined axiom. CI fails if
any of those appear, and fails if `#print axioms` shows a headline theorem
depending on `sorryAx`.

These theorems are statements about **the Lean model in `spec/Deflate/`**.

## What is not proved

- **The Rust code.** No refinement proof connects `crates/deflate-core` to
  the Lean model for milestones M1–M8. Following the M0 Charon/Aeneas spike
  outcome (ADR 0003), the differential harness in `oracles/` is the primary
  bridge, providing test evidence over a finite corpus. It says nothing
  about streams the corpus does not contain.
- **The executable.** File I/O, argument parsing, process startup, the
  allocator, the linker and the compiler are all outside the boundary
  (spec §6). `vdeflate` is never "formally verified".
- **`lean-zip` (commit `2f7a63f38195bc667a926881b55d10c9f8a88eeb`).** Its theorems are about its own Lean code. They never
  appear in the "Formally covered" column of `docs/conformance.md`
  (spec §13). It is used here as an independent reading of RFC 1951 in the
  differential harness.
- **Hash and arithmetic idealizations.** Where the model represents a
  quantity more abstractly than the Rust does, this document names it.

## Status

Updated at the end of every milestone. Current: M0 in progress; nothing
beyond `Deflate.byteAt_oob` is proved yet.
