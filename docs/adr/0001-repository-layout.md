# ADR 0001: Repository layout

**Status:** accepted · **Date:** 2026-10-05

## Context

Spec §5 gives a layout. The maked project, which this project's methodology
follows, uses a different one (`rust_make/` and `lean_make/` as sibling
build roots).

## Decision

Use spec §5's layout, with `Cargo.toml` and `lakefile.toml` both at the
repository root. Lake confines itself to `.lake/` and Cargo to `target/`, so
they coexist without conflict, and the spec's layout keeps specification,
verified core, generated artifacts, CLI and tests separated as §5 requires.

Adopt four things from maked that spec §5 does not mention:

- a top-level `Makefile` as the single driver (`make`, `make test`);
- `spec/scripts/axioms.lean` as a CI gate on the headline theorems;
- `docs/adr/` for decisions, per spec §20;
- `oracles/` for the differential harness, since `tests/differential/`
  in §5 holds data while the harness is a program.

## Consequences

`lake build` must be run from the repository root, not from `spec/`.
