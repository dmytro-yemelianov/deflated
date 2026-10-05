# ADR 0003: How the Rust core and the Lean model are connected

**Status:** accepted · **Date:** 2026-10-05

## Context

Spec §1 names Charon + Aeneas as the preferred bridge and §3.4 asks for
`Rust → Charon → LLBC → Aeneas → Lean 4`. Spec §7 warns not to implement the
whole decoder and only then discover the architecture cannot be translated,
which is why this spike is M0 and not M5.

The maked project, whose methodology this project follows, uses no extraction
at all: an executable Lean model beside the Rust, with a differential fuzzer
as the bridge and documents that say plainly there is no refinement proof.

## Decision

The **primary** bridge is maked's: the executable model in `spec/Deflate/`,
diffed against `crates/deflate-core` by `oracles/differential.py` over
generated and curated corpora. This is test evidence. It is what every
milestone depends on, and it cannot be blocked by a third-party tool.

Charon/Aeneas is a **secondary, additive** bridge, pursued only where it is
cheap. The spike result below decides whether later milestones carry a
translation step.

## Spike result

- **Charon version:** v0.1.284 (git `https://github.com/AeneasVerif/charon` commit `d3c5b7da`; build failed) · **Aeneas version:** none installed (not available in PATH)
- **Outcome:** not translated
- **Where it broke (if it did):** Building Charon from source failed against the project toolchain (`rustc 1.88.0`). Charon's dependency `libspecr` requires unstable nightly features (`#![feature(try_trait_v2)]`, `decl_macro`, `iterator_try_collect`, `step_trait`) resulting in `error[E0554]: #![feature] may not be used on the stable release channel` and trait mismatch `error[E0407]: method forward_overflowing is not a member of trait Step`. Furthermore, `aeneas` requires an extensive out-of-tree OCaml/Opam toolchain setup.
- **Decision for M1–M8:** no translation steps

## Consequences

`docs/verification-boundary.md` states the outcome in the terms a reader
needs: no refinement proof connects the Lean model and the Rust code; the
differential harness is the bridge — maked's own wording. Later milestones
(M1–M8) will not include Charon or Aeneas translation steps.
