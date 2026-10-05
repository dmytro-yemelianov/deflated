# Verification Directory

This directory contains artifacts, spikes, and evaluation results for the formal
Rust-to-Lean bridge investigated during Milestone M0.

## Purpose

Per spec §1, §3.4, and §7, the project investigated whether Charon and Aeneas
could form an automated translation and refinement pipeline from Rust to Lean 4:
`Rust → Charon → LLBC → Aeneas → Lean 4`.

The goal of the M0 spike was to determine whether this pipeline is viable and
maintainable for the DEFLATE bit-reader and core state transitions without
imposing fragile toolchain dependencies or blocking the overall roadmap.

## Directory Structure

- `charon/`: Standalone Rust code and inputs for Charon analysis (e.g. `spike.rs`).
- `generated/`: Lean 4 definitions translated by Aeneas from Charon's LLBC representation (if generated).
- `proofs/`: Formal Lean 4 refinement proofs connecting translated code to Lean specifications.

## Bridge Architecture and Decision

As recorded in [docs/adr/0003-rust-lean-bridge.md](../docs/adr/0003-rust-lean-bridge.md) and
[docs/verification-boundary.md](../docs/verification-boundary.md):

1. **Primary Bridge:** The differential testing harness in `oracles/` comparing the
   Rust implementation in `crates/deflate-core` directly against the executable Lean
   specification in `spec/Deflate/`.
2. **Secondary/Evaluated Bridge:** Charon/Aeneas was evaluated as a candidate for
   formal translation and refinement proofs. Because Charon and Aeneas require custom
   pinned compiler toolchains and extensive out-of-tree dependencies, no refinement
   proof connects the Lean model and Rust code for milestones M1–M8.
