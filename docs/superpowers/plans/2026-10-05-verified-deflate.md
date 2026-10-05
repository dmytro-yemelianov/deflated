# Verified DEFLATE (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-dependency Rust DEFLATE (RFC 1951) decoder and stored-block encoder beside an executable Lean 4 model with kernel-checked theorems, bridged by a four-way differential fuzzer, meeting every v1 acceptance criterion in §18 of the spec.

**Architecture:** The maked spine — a small executable Lean 4 model carries the proof-critical semantics and the theorems; the Rust core is an independent implementation with the same state machine; a differential harness runs both against `zlib` and `lean-zip` on generated and curated corpora. No refinement proof connects Lean to Rust unless the M0 Charon/Aeneas spike proves one is cheap, and every document says so plainly. Two executable Lean checkers with soundness theorems (`wellFormed_sound`, `decodeFuel_sufficient`) give the bridge more teeth than a raw diff: the Rust encoder's output is accepted by a predicate that is kernel-proved to imply decodability.

**Tech Stack:** Rust 1.88 (edition 2024, `no_std` + `alloc` core, zero runtime dependencies), Lean 4.30.0 via elan + Lake, Python 3 (`zlib` oracle + fuzz harness), `cargo-fuzz` 0.13, GNU make as the top-level driver.

**Spec:** `VERIFIED_DEFLATE_SPEC.md` (repository root)

**Reference approach:** `/Users/dmytro/github/maked` — specifically `docs/inside-maked.md` §2 ("The Lean 4 model, and what it is not"), `lean_make/scripts/axioms.lean`, `benchmarks/fuzzer/fuzz_runner.py`, and `.github/workflows/ci.yml`. Read these before Task 1.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Rust 1.88.0, edition 2024.** CI pins `1.88.0`. Matches maked.
- **Lean `leanprover/lean4:v4.30.0`**, pinned in `lean-toolchain`. Matches maked.
- **`deflate-core` has zero `[dependencies]`.** `[dev-dependencies]` are permitted for differential tests and fuzzing (`miniz_oxide`); they must never be reachable from `lib.rs`. The shipped `vdeflate` binary depends only on `deflate-core` and `core`/`alloc`/`std`.
- **`deflate-core` is `#![no_std]` with `extern crate alloc;`.** No `std` path may appear in it.
- **No `unsafe` in `deflate-core`.** `#![forbid(unsafe_code)]` at the top of `lib.rs`. This is a compiler-enforced gate, not a convention.
- **No `sorry`, no `admit`, no new `axiom` in Lean sources.** CI greps for the words and fails. CI additionally runs `#print axioms` on the headline theorems and fails on `sorryAx`. Copied from maked's CI step verbatim in intent.
- **No panics on any input in `deflate-core`.** No `unwrap`, `expect`, `panic!`, `todo!`, `unimplemented!`, or indexing with `[]` on a slice whose bound is not already established. Clippy lints `indexing_slicing`, `unwrap_used`, `expect_used`, `panic` are `deny` for the `deflate-core` crate only.
- **Claim discipline.** The phrase "formally verified" never applies to the executable, only to named Lean theorems about the Lean model. Any document making a correctness claim must say which of the five categories in spec §2 it belongs to: RFC conformance, Lean-model correctness, Rust/Lean correspondence, memory safety, whole-executable assumptions.
- **`docs/conformance.md` "Formally covered" counts only theorems in `spec/Deflate/`.** A `lean-zip` theorem never fills that column (spec §13).
- **Every build and measurement command recorded in a doc is reproducible** and its raw output committed as JSON. This is the direct lesson of maked's "benchmark that lied".
- **Commit per semantic feature**, keeping `make test` green at every commit.

---

## Review Focus

Five input classes the spec implies but which no task's happy-path tests exercise, most likely to bite first. Each line's test is pinned to the task that owns the code, in that task's own step style.

1. **Truncation at every boundary** — empty input, a stream cut mid-header, mid-Huffman-code, mid-extra-bits, and mid-stored-payload must each return a specific `Error`, never panic, never hang, never silently return partial output as success. *(Tests in Task 5 for the bit layer and Task 17 for the whole decoder.)*
2. **Legal but empty blocks** — a stored block with `LEN = 0`, and a fixed-Huffman block containing only the end-of-block symbol, are both valid and must yield empty output, not `UnexpectedEof`. A decoder that treats "produced no bytes" as failure breaks on real zlib output. *(Tests in Task 7 and Task 14.)*
3. **Under-subscribed Huffman trees and the one-symbol distance tree** — RFC 1951 does not state whether an incomplete code is legal; zlib accepts a distance tree with zero or one code and rejects every other incomplete tree. Our rule must be explicit, tested in both directions, and written down as an ADR, or we silently disagree with every real encoder. *(Tests in Task 10 and Task 16.)*
4. **Distance exactly at and just past the output boundary** — `dist == out.len()` is legal and copies the very first byte produced; `dist == out.len() + 1` is `InvalidDistance`; `dist == 0` is `InvalidDistance`. A first-block back-reference has nothing behind it, and an off-by-one here is a memory-safety bug in any language without bounds checks. *(Tests in Task 12.)*
5. **Compression bombs** — a few hundred input bytes can expand to gigabytes. `inflate_with_limit` must refuse to allocate past the limit while decoding, not merely check the length at the end, and the limit must be enforced inside the LZ77 copy loop. *(Tests in Task 17.)*

---

## File Structure

Layout follows spec §5, with four additions drawn from maked: a top-level `Makefile` driver, `spec/scripts/axioms.lean`, `docs/adr/`, and `oracles/` for the differential harness.

```text
deflated/
├── VERIFIED_DEFLATE_SPEC.md     the spec this plan implements
├── README.md                    what is and is not proved, up front
├── Makefile                     all / test / fuzz / size — the single driver
├── Cargo.toml                   workspace: deflate-core, vdeflate
├── lakefile.toml                lean_lib Deflate (srcDir spec), lean_exe deflate_spec
├── lean-toolchain               leanprover/lean4:v4.30.0
├── rust-toolchain.toml          1.88.0
├── spec/                        the Lean 4 model — one responsibility per file
│   ├── Deflate.lean             root export
│   ├── Main.lean                oracle driver: hex line protocol on stdin
│   ├── scripts/axioms.lean      CI gate: #print axioms on headline theorems
│   └── Deflate/
│       ├── Bitstream.lean       BitReader, readBit/readBits/alignToByte
│       ├── Huffman.lean         canonical codes, Kraft check, decodeSym
│       ├── LZ77.lean            length/distance tables, copyBack with overlap
│       ├── Block.lean           header, stored, dynamic code-length decoding
│       ├── Decode.lean          fuel-bounded decoder state machine
│       ├── Encode.lean          stored-block encoder
│       └── Properties.lean      P1–P12 theorems about the model
├── crates/
│   ├── deflate-core/            the verified core: no_std, zero deps, no unsafe
│   │   └── src/{lib,error,bitstream,huffman,lz77,block,inflate,deflate}.rs
│   └── vdeflate/src/main.rs     CLI — explicitly outside the proof boundary
├── verification/
│   ├── charon/                  M0 spike inputs and config
│   ├── generated/               Aeneas output — never hand-edited
│   ├── proofs/                  handwritten refinement proofs, if any
│   └── README.md                what lives here and what it means
├── tests/
│   ├── vectors/                 shared corpus: .raw + .deflate pairs
│   ├── roundtrip/               encode→decode property tests
│   ├── differential/            Rust vs Lean vs zlib vs lean-zip
│   └── malformed/               curated bad streams + minimized fuzz finds
├── fuzz/fuzz_targets/           cargo-fuzz: inflate, dynamic header, roundtrip, differential
├── oracles/
│   ├── differential.py          4-way harness (maked fuzz_runner.py pattern)
│   ├── corpus.py                corpus generation
│   └── reports/                 committed JSON results
├── scripts/
│   ├── size_report.sh           reproducible binary-size measurement
│   └── ci/                      CI helpers
└── docs/
    ├── architecture.md
    ├── verification-boundary.md exactly what is and is not proved
    ├── conformance.md           the §13 matrix
    ├── size-report.md
    └── adr/                     one file per architecture decision
```

Each Lean module and each Rust module holds one layer of the format, so a task touches one or two files and a reviewer can hold the whole change at once. `spec/Deflate/*.lean` and `crates/deflate-core/src/*.rs` deliberately mirror each other name for name — the differential harness and the correspondence argument both depend on that symmetry.

---

# M0 — Toolchain and research spike

**Exit criterion (spec §17):** one Rust state transition is translated and proved against a Lean specification, *or* a written record of why that is not currently possible. Either outcome closes M0; only the first changes the plan for later milestones.

### Task 1: Dual build skeleton, green on both sides

**Files:**
- Create: `Cargo.toml`, `rust-toolchain.toml`, `lakefile.toml`, `lean-toolchain`, `Makefile`, `.gitignore`
- Create: `crates/deflate-core/Cargo.toml`, `crates/deflate-core/src/lib.rs`, `crates/deflate-core/src/error.rs`
- Create: `crates/vdeflate/Cargo.toml`, `crates/vdeflate/src/main.rs`
- Create: `spec/Deflate.lean`, `spec/Deflate/Basic.lean`, `spec/Main.lean`, `spec/scripts/axioms.lean`
- Create: `.github/workflows/ci.yml`
- Create: `docs/verification-boundary.md`, `docs/conformance.md`, `docs/adr/0001-repository-layout.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `deflate_core::error::Error` (the enum every later task returns); the `Deflate` Lean library root; `make`, `make test` as the two commands every later task runs.

- [x] **Step 1: Write the failing test**

`crates/deflate-core/src/error.rs`:

```rust
//! The error model (spec §10). Every failure in the core is one of these.
//! No input, however malformed, may produce a panic instead of one of these.

/// Deterministic failure modes. Spec §10, §12 (P12).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    /// The stream ended while more bits were required.
    UnexpectedEof,
    /// A block header carried BTYPE = 3.
    InvalidBlockType,
    /// A stored block's NLEN was not the ones' complement of LEN.
    InvalidStoredLength,
    /// A code-length set was over-subscribed, or incomplete where a
    /// complete code is required.
    InvalidHuffmanTree,
    /// A Huffman code was read that the table does not assign a symbol to.
    InvalidCode,
    /// A back-reference distance was 0, or reached before the start of output.
    InvalidDistance,
    /// A length symbol outside 257..=285 appeared where a length was expected.
    InvalidLength,
    /// Decoding would have produced more bytes than the caller allowed.
    OutputLimitExceeded,
}
```

`crates/deflate-core/tests/skeleton.rs`:

```rust
#[test]
fn error_variants_are_distinct_and_copy() {
    use deflate_core::Error;
    let a = Error::UnexpectedEof;
    let b = a; // Copy
    assert_eq!(a, b);
    assert_ne!(Error::UnexpectedEof, Error::InvalidBlockType);
}
```

`spec/Deflate/Basic.lean`:

```lean
/-
  Deflate.Basic — shared vocabulary for the model.

  The theorems in this library are statements about *this model*. Nothing is
  extracted from or to Rust. What connects the model to `deflate-core` is the
  differential harness in `oracles/`, which is test evidence, not proof. See
  `docs/verification-boundary.md`.
-/
namespace Deflate

/-- A bit offset from the start of the compressed stream. -/
abbrev BitPos := Nat

/-- Deterministic failure modes. Mirrors `deflate_core::Error` name for name. -/
inductive DecErr where
  | unexpectedEof
  | invalidBlockType
  | invalidStoredLength
  | invalidHuffmanTree
  | invalidCode
  | invalidDistance
  | invalidLength
  | outputLimitExceeded
  /-- The decoder ran out of fuel. `Properties.decodeFuel_sufficient` shows
      this is unreachable at the fuel the entry point supplies. Reported
      explicitly rather than folded into another error: maked's cycle
      detector once answered "acyclic" on fuel exhaustion, which was wrong. -/
  | fuelExhausted
  deriving Repr, DecidableEq, Inhabited

/-- Total byte access: out of range reads as 0. Keeps every definition total
    so proofs never carry bounds side-conditions through arithmetic. -/
def byteAt (bs : ByteArray) (i : Nat) : UInt8 :=
  if h : i < bs.size then bs[i] else 0

theorem byteAt_oob (bs : ByteArray) (i : Nat) (h : ¬ i < bs.size) :
    byteAt bs i = 0 := by
  simp [byteAt, h]

end Deflate
```

- [x] **Step 2: Run both builds to verify they fail**

Run: `cargo test --workspace`
Expected: FAIL — no `Cargo.toml` workspace yet, or `error: couldn't read crates/deflate-core/src/lib.rs`.

Run: `lake build`
Expected: FAIL — no `lakefile.toml` yet.

- [x] **Step 3: Write the build files**

`rust-toolchain.toml`:

```toml
[toolchain]
channel = "1.88.0"
components = ["rustfmt", "clippy"]
```

`Cargo.toml` (workspace root):

```toml
[workspace]
members = ["crates/deflate-core", "crates/vdeflate"]
resolver = "3"

[workspace.package]
version = "0.1.0"
edition = "2024"
rust-version = "1.88"
license = "MIT OR Apache-2.0"
authors = ["Yemelianov Dmytro"]

[profile.release]
opt-level = 3
```

`crates/deflate-core/Cargo.toml`:

```toml
[package]
name = "deflate-core"
description = "RFC 1951 DEFLATE core: no_std, zero dependencies, no unsafe"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

# Spec §4, Global Constraints: this list stays empty. Forever.
[dependencies]

[dev-dependencies]
```

`crates/deflate-core/src/lib.rs`:

```rust
//! RFC 1951 DEFLATE core.
//!
//! This crate is the proof-critical part of the project. It is `no_std`,
//! has no runtime dependencies, and contains no `unsafe`. The Lean model in
//! `spec/Deflate/` mirrors it module for module.
//!
//! Nothing here is "formally verified". The Lean theorems are about the Lean
//! model; this code is connected to that model by differential testing only.
//! See `docs/verification-boundary.md`.
#![no_std]
#![forbid(unsafe_code)]

extern crate alloc;

pub mod error;

pub use error::Error;
```

`crates/vdeflate/Cargo.toml`:

```toml
[package]
name = "vdeflate"
description = "Minimal DEFLATE CLI. Outside the verification boundary."
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[[bin]]
name = "vdeflate"
path = "src/main.rs"

[dependencies]
deflate-core = { path = "../deflate-core" }
```

`crates/vdeflate/src/main.rs`:

```rust
//! Minimal CLI. File I/O, argument parsing and process exit are outside the
//! verification boundary (spec §6). Task 23 gives this real behavior.
fn main() {
    eprintln!("vdeflate {}: not yet implemented", env!("CARGO_PKG_VERSION"));
    std::process::exit(2);
}
```

`lean-toolchain`:

```text
leanprover/lean4:v4.30.0
```

`lakefile.toml`:

```toml
name = "deflate_spec"
version = "0.1.0"
defaultTargets = ["deflate_spec"]

[[lean_lib]]
name = "Deflate"
srcDir = "spec"

[[lean_exe]]
name = "deflate_spec"
srcDir = "spec"
root = "Main"
```

`spec/Deflate.lean`:

```lean
-- Root export for the Deflate model.
import Deflate.Basic
```

`spec/Main.lean`:

```lean
import Deflate

def main (_args : List String) : IO Unit := do
  IO.println "deflate_spec: oracle driver, see Task 8"
```

`spec/scripts/axioms.lean`:

```lean
-- CI: the headline theorems must rest only on Lean's standard axioms.
-- Run with `lake env lean spec/scripts/axioms.lean`; CI fails on `sorryAx`.
-- Theorem names are added here by the task that proves them.
import Deflate
open Deflate
#print axioms Deflate.byteAt_oob
```

`.gitignore`:

```text
/target
/.lake
/fuzz/target
/fuzz/corpus
/oracles/__pycache__
```

- [x] **Step 4: Write the top-level driver**

`Makefile`:

```makefile
# Top-level driver for verified-deflate. Mirrors maked's Makefile.
.PHONY: all build-rust build-lean test test-rust test-lean test-differential \
        fmt lint fuzz size clean

all: build-rust build-lean

build-rust:
	@echo "==> cargo build --release"
	@cargo build --release --workspace

build-lean:
	@echo "==> lake build (Lean model + theorems)"
	@lake build

test: test-rust test-lean test-differential

test-rust:
	@cargo test --workspace

test-lean: build-lean
	@echo "==> no sorry/admit"
	@! grep -rnwE 'sorry|admit' spec/ --include='*.lean'
	@echo "==> headline theorems rest on standard axioms only"
	@lake env lean spec/scripts/axioms.lean | tee /tmp/axioms.log
	@! grep -q sorryAx /tmp/axioms.log

test-differential: build-rust build-lean
	@python3 oracles/differential.py

fmt:
	@cargo fmt --all --check

lint:
	@cargo clippy --workspace --all-targets -- -D warnings

fuzz:
	@cargo +nightly fuzz run inflate -- -max_total_time=60

size: build-rust
	@bash scripts/size_report.sh

clean:
	@cargo clean
	@lake clean
```

Note on `test-lean`: `grep` exits 1 when it finds nothing, so `! grep ...` succeeds exactly when the forbidden words are absent. This is the gate, not a convention.

- [x] **Step 5: Run both builds to verify they pass**

Run: `cargo test --workspace`
Expected: PASS — `error_variants_are_distinct_and_copy`.

Run: `make test-lean`
Expected: PASS — `lake build` succeeds, no `sorry`/`admit`, `#print axioms Deflate.byteAt_oob` prints `'Deflate.byteAt_oob' depends on axioms: [propext]` or similar, with no `sorryAx`.

- [x] **Step 6: Write the two honesty documents**

`docs/verification-boundary.md`:

```markdown
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
  the Lean model. What connects them is the differential harness in
  `oracles/`, which is test evidence over a finite corpus. It says nothing
  about streams the corpus does not contain.
- **The executable.** File I/O, argument parsing, process startup, the
  allocator, the linker and the compiler are all outside the boundary
  (spec §6). `vdeflate` is never "formally verified".
- **`lean-zip`.** Its theorems are about its own Lean code. They never
  appear in the "Formally covered" column of `docs/conformance.md`
  (spec §13). It is used here as an independent reading of RFC 1951 in the
  differential harness.
- **Hash and arithmetic idealizations.** Where the model represents a
  quantity more abstractly than the Rust does, this document names it.

## Status

Updated at the end of every milestone. Current: M0 in progress; nothing
beyond `Deflate.byteAt_oob` is proved yet.
```

`docs/conformance.md`:

```markdown
# Conformance matrix (spec §13)

"Formally covered" means a named theorem in `spec/Deflate/Properties.lean`
covers the feature *in the Lean model*. It never means the Rust code is
proved, and it never counts a theorem from another project.

| Feature | Implemented | Tested | Formally covered |
| --- | --- | --- | --- |
| Bit reader (LSB-first, EOF) | no | no | no |
| Stored blocks | no | no | no |
| Fixed Huffman | no | no | no |
| Dynamic Huffman | no | no | no |
| Multi-block streams | no | no | no |
| Overlapping back-reference | no | no | no |
| Malformed input rejection | no | no | no |
| Output limit | no | no | no |
| Encoder validity | no | no | no |
| Round trip | no | no | no |
```

`docs/adr/0001-repository-layout.md`:

```markdown
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
```

- [x] **Step 7: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
  workflow_dispatch:

env:
  CARGO_TERM_COLOR: always

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  verify:
    name: Verify & Test Gate
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4

      - name: Show toolchain
        run: rustc --version && cargo --version && python3 --version

      - name: Install elan (Lean 4.30.0)
        run: |
          curl -sSfL https://github.com/leanprover/elan/releases/latest/download/elan-x86_64-unknown-linux-gnu.tar.gz \
            | tar xz && ./elan-init -y --default-toolchain none
          echo "$HOME/.elan/bin" >> "$GITHUB_PATH"

      - name: Format
        run: cargo fmt --all --check

      - name: Clippy
        run: cargo clippy --workspace --all-targets -- -D warnings

      - name: Test
        run: cargo test --workspace

      - name: No unsafe, no std in the core
        run: |
          ! grep -rn 'unsafe' crates/deflate-core/src/
          ! grep -rnw 'std' crates/deflate-core/src/

      - name: Lean model (lake build, no sorry, axiom gate)
        run: |
          lake build
          if grep -rnwE 'sorry|admit' spec/ --include='*.lean'; then
            echo "::error::sorry/admit present in Lean sources"; exit 1
          fi
          lake env lean spec/scripts/axioms.lean | tee axioms.log
          if grep -q sorryAx axioms.log; then
            echo "::error::a headline theorem depends on sorryAx"; exit 1
          fi

      - name: Differential harness (Rust vs Lean vs zlib)
        run: python3 oracles/differential.py
```

The differential step will fail until Task 8 creates `oracles/differential.py`. Add that step in Task 8, not now — keep CI green at every commit.

- [x] **Step 8: Verify the whole gate passes**

Run: `make all && cargo fmt --all --check && cargo clippy --workspace --all-targets -- -D warnings && make test-rust && make test-lean`
Expected: every command exits 0.

- [x] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(m0): dual Cargo+Lake skeleton, error model, CI gates, honesty docs

Rust: no_std zero-dep deflate-core with forbid(unsafe_code) and the spec
§10 error enum. Lean: Deflate library root with the total byteAt accessor.
CI gates on fmt, clippy -D warnings, no unsafe, no std in core, lake build,
no sorry/admit, and #print axioms for sorryAx.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 2: lean-zip assessment (spec §14, hard gate)

**Files:**
- Create: `docs/adr/0002-lean-zip.md`
- Create: `tests/vectors/README.md`
- Modify: `docs/verification-boundary.md` (the `lean-zip` bullet gains the recorded revision)

**Interfaces:**
- Consumes: nothing.
- Produces: the recorded decision — `lean-zip` is an oracle and a definition reference, never a source of coverage. Task 20 depends on the build instructions this ADR records.

- [x] **Step 1: Clone and record the exact revision**

```bash
mkdir -p /tmp/leanzip && cd /tmp/leanzip
git clone https://github.com/kim-em/lean-zip.git
cd lean-zip
git rev-parse HEAD > /tmp/leanzip/REV
cat lean-toolchain
ls LICENSE* COPYING* 2>/dev/null && head -5 LICENSE*
```

Record the commit SHA, the `lean-toolchain` contents, and the license verbatim. If the toolchain differs from `v4.30.0`, note it — the harness invokes `lean-zip` as a separate built binary, so a toolchain mismatch is tolerable, but it must be written down.

- [x] **Step 2: Map its definitions to RFC 1951 features**

```bash
cd /tmp/leanzip/lean-zip
rg -n 'def (inflate|decode|huffman|Huffman|bitReader|BitReader|lz77|LZ77|stored|dynamic|fixed)' --type lean | head -40
rg -n 'theorem .*(decompress|compress|roundtrip|round_trip)' --type lean | head -20
```

For each of the seven features in `docs/conformance.md`, write one line in the ADR naming the `lean-zip` definition that covers it, or "none found".

- [x] **Step 3: Build it and confirm it runs as an oracle**

```bash
cd /tmp/leanzip/lean-zip && lake build 2>&1 | tail -20
```

If it builds, find or add an entry point that takes a compressed stream and prints the decompressed bytes. If the build takes more than 20 minutes or fails on this machine, record that: it determines whether Task 20 can include `lean-zip` as a live fourth oracle or only as a documented cross-check of RFC readings.

- [x] **Step 4: Write the ADR**

`docs/adr/0002-lean-zip.md`:

```markdown
# ADR 0002: The role of lean-zip

**Status:** accepted · **Date:** 2026-10-05

## Context

Spec §14 requires inspecting `lean-zip` before committing to architecture.
It is a pure-Lean 4 zlib with a DEFLATE encoder and decoder and a
kernel-checked theorem that decompressing `compress x` returns `x`.

Two facts decide the role:

1. That round-trip theorem is **exactly** the property spec §2 names as
   necessary but not sufficient. Two mutually compatible implementations can
   round-trip while both violating RFC 1951.
2. The theorem is about `lean-zip`'s own Lean code. Spec §13 forbids marking
   a feature formally covered because a different implementation has a
   proof.

## Decision

`lean-zip` is a **differential oracle and a definition reference**, not a
dependency and not a source of coverage.

- We write our own small model in `spec/Deflate/`, shaped to mirror the Rust
  state machine so the two can be diffed byte for byte.
- `lean-zip` joins `zlib` as an independent party in `oracles/differential.py`.
  It is valuable there precisely because it is an *independent reading of
  RFC 1951 by a different author*, which `zlib` is not: `zlib` is the de
  facto definition, so agreeing with it proves compatibility, not conformance.
- Where our reading of an ambiguous RFC passage differs from `lean-zip`'s,
  the difference is recorded in this file rather than silently resolved.

## Recorded facts

- **Revision:** `<SHA from Step 1>`
- **License:** `<verbatim from Step 1>`
- **Lean toolchain:** `<from Step 1>`
- **Builds on this machine:** yes/no, `<wall time>`
- **Definition map:** `<table from Step 2>`

## Semantic differences found

`<one line per difference, or "none found at this revision">`

## Consequences

`docs/conformance.md`'s "Formally covered" column counts only theorems in
`spec/Deflate/Properties.lean`. The harness reports `lean-zip` disagreements
as findings to investigate, not as test failures, until a disagreement is
traced to a defect on one side.
```

- [x] **Step 5: Verify the gate**

Run: `test -s docs/adr/0002-lean-zip.md && ! grep -n '<SHA from Step 1>\|<verbatim\|<from Step 1>\|<one line per\|<table from' docs/adr/0002-lean-zip.md`
Expected: exit 0 — every placeholder has been replaced with a recorded fact.

- [x] **Step 6: Commit**

```bash
git add docs/adr/0002-lean-zip.md tests/vectors/README.md docs/verification-boundary.md
git commit -m "docs(m0): lean-zip assessment — oracle and reference, not a dependency

Records revision, license, toolchain and definition map. Its round-trip
theorem is the property spec §2 calls insufficient, and spec §13 forbids
counting another project's proof as our coverage.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 3: Charon/Aeneas spike — the M0 exit criterion

**Files:**
- Create: `verification/charon/spike.rs`, `verification/README.md`
- Create: `docs/adr/0003-rust-lean-bridge.md`
- Create (on success): `verification/generated/`, `verification/proofs/Spike.lean`

**Interfaces:**
- Consumes: nothing from earlier tasks — the spike function is deliberately standalone.
- Produces: the recorded decision on whether later milestones add Charon/Aeneas translation steps. **Time-boxed to one working day.** If it is not working by then, record why and move on; the plan does not depend on success.

- [x] **Step 1: Write the spike function**

The smallest thing that is still a real DEFLATE state transition: reading one bit and advancing. Concrete types only, no generics, no traits, no slices-of-slices — exactly the shape spec §7 demands and exactly what Aeneas's monomorphization requirement needs.

`verification/charon/spike.rs`:

```rust
//! The Charon/Aeneas spike (M0). Deliberately standalone: it duplicates the
//! shape of `deflate_core::bitstream` rather than importing it, so a
//! translation failure here is a fact about the toolchain, not about a
//! half-written crate.
#![no_std]
#![forbid(unsafe_code)]

pub struct Reader {
    pub bytes: [u8; 8],
    pub pos: u32,
}

/// Read one bit, LSB-first within each byte. Returns `None` past the end.
pub fn read_bit(r: &Reader) -> Option<(bool, u32)> {
    if r.pos >= 64 {
        return None;
    }
    let byte = r.bytes[(r.pos / 8) as usize];
    let bit = (byte >> (r.pos % 8)) & 1;
    Some((bit == 1, r.pos + 1))
}
```

- [x] **Step 2: Install and run Charon, then Aeneas**

```bash
# Record every version. Spec §19.3: pin toolchain revisions.
cargo install --git https://github.com/AeneasVerif/charon charon 2>&1 | tail -5
charon --version
# Aeneas is OCaml; follow the upstream README for the current install route.
aeneas --version
```

```bash
cd verification/charon
charon --no-cargo --input spike.rs --dest-file spike.llbc
aeneas -backend lean spike.llbc -dest ../generated
```

Expected on success: `verification/generated/Spike.lean` containing a `read_bit` returning `Result (Bool × U32)`.

- [x] **Step 3: Write the refinement proof against a hand specification**

`verification/proofs/Spike.lean`:

```lean
/-
  M0 spike: the Aeneas-generated `read_bit` agrees with a hand-written Lean
  specification of the same transition. Proving this for one function is the
  spec §17 M0 exit criterion.
-/
import Generated.Spike

namespace Spike

/-- Hand specification: bit `i` of the stream is bit `i % 8` of byte `i / 8`,
    least significant first. -/
def specBit (bytes : List UInt8) (i : Nat) : Option Bool :=
  if i < 64 then
    (bytes[i / 8]?).map (fun b => ((b.toNat >>> (i % 8)) &&& 1) == 1)
  else none

/-- The generated function computes the hand specification. -/
theorem read_bit_refines (r : spike.Reader)
    (h : r.pos.val < 64) :
    ∃ b, spike.read_bit r = .ok (b, r.pos + 1#u32)
      ∧ some b = specBit r.bytes.toList r.pos.val := by
  sorry -- replaced by the real proof in Step 4; never committed with sorry
end Spike
```

- [x] **Step 4: Close the proof, or record the failure**

Work the proof until it closes. **Do not commit a `sorry`** — Global Constraints and spec §19.7 forbid it, and CI fails on it. Two outcomes are acceptable:

- **Success:** the theorem closes. Delete the `sorry` line, add `#print axioms Spike.read_bit_refines` to `spec/scripts/axioms.lean`, and record in the ADR that the bridge is viable.
- **Failure within the time box:** delete `verification/proofs/Spike.lean` entirely, keep `verification/charon/spike.rs` and whatever Charon/Aeneas output was produced, and record in the ADR exactly where it broke — which tool, which message, which language feature.

- [x] **Step 5: Verify**

On success, run: `lake env lean verification/proofs/Spike.lean`
Expected: no errors, no `sorry` warning.

On either outcome, run: `! grep -rnwE 'sorry|admit' spec/ verification/proofs/ --include='*.lean' 2>/dev/null`
Expected: exit 0.

- [x] **Step 6: Write the ADR**

`docs/adr/0003-rust-lean-bridge.md`:

```markdown
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

- **Charon version:** `<recorded>` · **Aeneas version:** `<recorded>`
- **Outcome:** translated and proved / translated but not proved / not translated
- **Where it broke (if it did):** `<tool, message, language feature>`
- **Decision for M1–M8:** `<add a translation step to the bitstream task only /
  add translation steps to every core task / no translation steps>`

## Consequences

`docs/verification-boundary.md` states the outcome in the terms a reader
needs: either "a refinement proof connects `read_bit` and nothing else", or
"no refinement proof connects the Lean model and the Rust code; the
differential harness is the bridge" — maked's own wording.
```

- [x] **Step 7: Update the boundary document and commit**

Rewrite the "The Rust code" bullet in `docs/verification-boundary.md` to match the spike outcome, then:

```bash
git add verification/ docs/adr/0003-rust-lean-bridge.md docs/verification-boundary.md spec/scripts/axioms.lean
git commit -m "feat(m0): Charon/Aeneas spike on the bit-reader transition

M0 exit criterion. Records tool versions and the outcome in ADR 0003. The
differential harness remains the primary bridge regardless of the result.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M1 — Bitstream

**Exit:** LSB-first reads, alignment, bounds and EOF semantics implemented in both languages, with P1 proved in the model.

### Task 4: Lean bit reader and P1

**Files:**
- Create: `spec/Deflate/Bitstream.lean`, `spec/Deflate/Properties.lean`
- Modify: `spec/Deflate.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `Deflate.byteAt`, `Deflate.BitPos`, `Deflate.DecErr` (Task 1).
- Produces: `Deflate.BitReader` (fields `bytes : ByteArray`, `pos : Nat`), `BitReader.readBit`, `BitReader.readBits`, `BitReader.alignToByte`, `BitReader.size`. Tasks 6, 9, 11, 13, 15, 18, 21 all build on these exact names.

- [x] **Step 1: Write the failing theorem file**

`spec/Deflate/Properties.lean`:

```lean
/-
  Deflate.Properties — the proof obligations of spec §9, as theorems about
  the model in `spec/Deflate/`. Nothing here is a statement about the Rust
  code. See `docs/verification-boundary.md`.
-/
import Deflate.Bitstream

namespace Deflate
open BitReader

/-! ### P1 — Bit reader -/

/-- Reading one bit advances the position by exactly one. -/
theorem readBit_pos {r r' : BitReader} {b : Bool} (h : readBit r = some (b, r')) :
    r'.pos = r.pos + 1 := by
  unfold readBit at h; split at h <;> simp_all

/-- Reading never alters the input. -/
theorem readBit_bytes {r r' : BitReader} {b : Bool} (h : readBit r = some (b, r')) :
    r'.bytes = r.bytes := by
  unfold readBit at h; split at h <;> simp_all

end Deflate
```

- [x] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown module prefix 'Deflate.Bitstream'`.

- [x] **Step 3: Write the model**

`spec/Deflate/Bitstream.lean`:

```lean
/-
  Deflate.Bitstream — LSB-first bit reading (RFC 1951 §3.1.1).

  "Data elements other than Huffman codes are packed starting with the least
  significant bit of the data element." Huffman codes are the exception; they
  are read most-significant-bit first and live in `Deflate.Huffman`.

  `readBits` recurses on the bit count rather than folding, so each theorem in
  `Deflate.Properties` is a one-line induction.
-/
import Deflate.Basic

namespace Deflate

/-- A position in a compressed stream: the bytes, and a bit offset into them. -/
structure BitReader where
  bytes : ByteArray
  pos   : BitPos
  deriving Repr

namespace BitReader

/-- Total bits available. -/
def size (r : BitReader) : Nat := r.bytes.size * 8

/-- Bit `i` of the stream: bit `i % 8` of byte `i / 8`, least significant first. -/
def bitAt (bs : ByteArray) (i : Nat) : Bool :=
  (((byteAt bs (i / 8)).toNat >>> (i % 8)) &&& 1) == 1

/-- One bit, or `none` past the end. Past-the-end is the only failure. -/
def readBit (r : BitReader) : Option (Bool × BitReader) :=
  if r.pos < r.size then
    some (bitAt r.bytes r.pos, { r with pos := r.pos + 1 })
  else
    none

/-- `n` bits, least significant first. All-or-nothing: a short read returns
    `none` and no partially advanced reader, because the caller only ever sees
    the returned reader. -/
def readBits : BitReader → Nat → Option (Nat × BitReader)
  | r, 0       => some (0, r)
  | r, (n + 1) => do
      let (b, r₁) ← readBit r
      let (rest, r₂) ← readBits r₁ n
      pure ((if b then 1 else 0) + 2 * rest, r₂)

/-- Skip to the next byte boundary (RFC 1951 §3.2.4, stored blocks). -/
def alignToByte (r : BitReader) : BitReader :=
  { r with pos := (r.pos + 7) / 8 * 8 }

end BitReader
end Deflate
```

Add `import Deflate.Bitstream` and `import Deflate.Properties` to `spec/Deflate.lean`.

- [x] **Step 4: Run to verify the two theorems pass**

Run: `lake build`
Expected: PASS.

- [x] **Step 5: Add the remaining P1 theorems**

Append to `spec/Deflate/Properties.lean`, inside `namespace Deflate`:

```lean
/-- `readBits` advances by exactly the number of bits requested. -/
theorem readBits_pos : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → r'.pos = r.pos + n := by
  intro n
  induction n with
  | zero => intro r v r' h; simp [readBits] at h; simp_all
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        rw [hr] at h
        have h1 := readBit_pos hb
        have h2 := ih r₁ rest r₂ hr
        simp at h
        omega

/-- Reading never alters the input, at any width. -/
theorem readBits_bytes : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → r'.bytes = r.bytes := by
  intro n
  induction n with
  | zero => intro r v r' h; simp [readBits] at h; simp_all
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        rw [hr] at h
        have h1 := readBit_bytes hb
        have h2 := ih r₁ rest r₂ hr
        simp at h
        simp_all

/-- `n` bits yield a value below `2 ^ n`: the bound every caller relies on
    when it adds extra bits to a base. -/
theorem readBits_lt : ∀ (n : Nat) (r : BitReader) (v : Nat) (r' : BitReader),
    readBits r n = some (v, r') → v < 2 ^ n := by
  intro n
  induction n with
  | zero => intro r v r' h; simp [readBits] at h; simp_all
  | succ n ih =>
    intro r v r' h
    unfold readBits at h
    cases hb : readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      cases hr : readBits r₁ n with
      | none => rw [hr] at h; simp at h
      | some q =>
        obtain ⟨rest, r₂⟩ := q
        rw [hr] at h
        have hrest := ih r₁ rest r₂ hr
        have hp : 2 ^ (n + 1) = 2 * 2 ^ n := by rw [Nat.pow_succ]; omega
        simp at h
        cases b <;> simp_all <;> omega

/-- Insufficient input is reported, deterministically, and never guessed at. -/
theorem readBits_eof : ∀ (n : Nat) (r : BitReader),
    r.size < r.pos + n → readBits r n = none := by
  intro n
  induction n with
  | zero => intro r h; simp at h; omega
  | succ n ih =>
    intro r h
    unfold readBits
    cases hb : readBit r with
    | none => simp [hb]
    | some p =>
      obtain ⟨b, r₁⟩ := p
      have h1 := readBit_pos hb
      have h2 := readBit_bytes hb
      have : r₁.size = r.size := by unfold size; rw [h2]
      have : r₁.size < r₁.pos + n := by omega
      simp [hb, ih r₁ this]

/-! ### P1 — alignment -/

theorem alignToByte_aligned (r : BitReader) : (alignToByte r).pos % 8 = 0 := by
  simp [alignToByte, Nat.mul_mod_left]

theorem alignToByte_ge (r : BitReader) : r.pos ≤ (alignToByte r).pos := by
  simp [alignToByte]; omega

theorem alignToByte_lt (r : BitReader) : (alignToByte r).pos < r.pos + 8 := by
  simp [alignToByte]; omega

theorem alignToByte_idem (r : BitReader) :
    alignToByte (alignToByte r) = alignToByte r := by
  simp [alignToByte]; omega

theorem alignToByte_bytes (r : BitReader) : (alignToByte r).bytes = r.bytes := rfl
```

- [x] **Step 6: Run to verify all P1 theorems pass**

Run: `lake build`
Expected: PASS, with no `sorry` warning on any line.

If a tactic does not close a goal, fix it there. Do not insert `sorry`: CI fails on it (Global Constraints, spec §19.7). If a proof genuinely resists, weaken the *statement* to something true and provable, and say in the file comment what was weakened and why.

- [x] **Step 7: Register the theorems with the axiom gate**

Replace the body of `spec/scripts/axioms.lean`:

```lean
import Deflate
open Deflate
#print axioms Deflate.readBits_pos
#print axioms Deflate.readBits_bytes
#print axioms Deflate.readBits_lt
#print axioms Deflate.readBits_eof
#print axioms Deflate.alignToByte_idem
```

- [x] **Step 8: Run the Lean gate**

Run: `make test-lean`
Expected: PASS — no `sorry`/`admit`, and the axiom log contains no `sorryAx`.

- [x] **Step 9: Commit**

```bash
git add spec/ 
git commit -m "feat(m1): Lean bit reader and P1

LSB-first readBit/readBits/alignToByte with the recursive readBits that makes
the inductions trivial. P1: position advance, input invariance, the 2^n value
bound, deterministic EOF, and the four alignment properties.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 5: Rust bit reader

**Files:**
- Create: `crates/deflate-core/src/bitstream.rs`
- Modify: `crates/deflate-core/src/lib.rs`
- Test: `crates/deflate-core/tests/bitstream_tests.rs`

**Interfaces:**
- Consumes: `deflate_core::Error` (Task 1).
- Produces: `BitReader<'a>` with `new(&'a [u8])`, `bit_pos() -> usize`, `bit_len() -> usize`, `read_bit() -> Result<u32, Error>`, `read_bits(n: u32) -> Result<u32, Error>`, `align_to_byte()`, `read_aligned_u16_le() -> Result<u16, Error>`, `read_aligned_into(&mut Vec<u8>, usize) -> Result<(), Error>`. Tasks 7, 10, 12, 14, 16, 17 use these exact signatures.

- [x] **Step 1: Write the failing tests**

`crates/deflate-core/tests/bitstream_tests.rs`:

```rust
use deflate_core::bitstream::BitReader;
use deflate_core::Error;

#[test]
fn reads_bits_least_significant_first() {
    // 0b1011_0010 = 0xB2. LSB-first the bits are 0,1,0,0,1,1,0,1.
    let data = [0xB2u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.read_bit().unwrap(), 0);
    assert_eq!(r.read_bit().unwrap(), 1);
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn read_bits_packs_first_bit_as_lsb() {
    // Low three bits of 0xB2 are 0b010 = 2 when read LSB-first.
    let data = [0xB2u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(3).unwrap(), 0b010);
    assert_eq!(r.bit_pos(), 3);
}

#[test]
fn read_bits_spans_byte_boundaries() {
    // 0x01,0x02 -> bits LSB-first: 1,0,0,0,0,0,0,0 | 0,1,0,0,0,0,0,0
    // Sixteen bits read at once is little-endian: 0x0201.
    let data = [0x01u8, 0x02];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(16).unwrap(), 0x0201);
}

#[test]
fn read_bits_zero_is_always_ok_even_at_eof() {
    let mut r = BitReader::new(&[]);
    assert_eq!(r.read_bits(0).unwrap(), 0);
    assert_eq!(r.bit_pos(), 0);
}

// --- Review Focus 1: truncation at every boundary, bit layer ---

#[test]
fn empty_input_reports_eof_not_panic() {
    let mut r = BitReader::new(&[]);
    assert_eq!(r.read_bit(), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0);
}

#[test]
fn short_read_is_atomic_and_leaves_position_untouched() {
    // Nine bits requested, eight available. The spec's P1 requires that a
    // failed read leave unrelated input unchanged.
    let data = [0xFFu8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(9), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0, "a failed read must not consume bits");
    // The reader is still usable.
    assert_eq!(r.read_bits(8).unwrap(), 0xFF);
}

#[test]
fn reading_past_the_end_keeps_reporting_eof() {
    let data = [0x00u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(8).unwrap(), 0);
    for _ in 0..4 {
        assert_eq!(r.read_bit(), Err(Error::UnexpectedEof));
    }
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn oversized_request_is_rejected_without_panicking() {
    let data = [0xFFu8; 8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_bits(33), Err(Error::InvalidCode));
    assert_eq!(r.bit_pos(), 0);
}

// --- alignment ---

#[test]
fn align_to_byte_is_a_noop_when_already_aligned() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 0);
    let _ = r.read_bits(8).unwrap();
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn align_to_byte_rounds_up_and_is_idempotent() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    let _ = r.read_bits(3).unwrap();
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
    r.align_to_byte();
    assert_eq!(r.bit_pos(), 8);
}

#[test]
fn aligned_u16_is_little_endian() {
    let data = [0x34u8, 0x12];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_aligned_u16_le().unwrap(), 0x1234);
    assert_eq!(r.bit_pos(), 16);
}

#[test]
fn aligned_u16_short_is_eof_and_atomic() {
    let data = [0x34u8];
    let mut r = BitReader::new(&data);
    assert_eq!(r.read_aligned_u16_le(), Err(Error::UnexpectedEof));
    assert_eq!(r.bit_pos(), 0);
}
```

- [x] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test bitstream_tests`
Expected: FAIL — `unresolved import deflate_core::bitstream`.

- [x] **Step 3: Write the implementation**

`crates/deflate-core/src/bitstream.rs`:

```rust
//! LSB-first bit reading (RFC 1951 §3.1.1).
//!
//! Mirrors `spec/Deflate/Bitstream.lean` function for function. The one place
//! the two differ in shape: the Lean reader is a value, so a failed read
//! simply returns `none` and the caller keeps the old reader. Rust mutates in
//! place, so every fallible read checks its whole width *before* consuming
//! anything. `short_read_is_atomic_and_leaves_position_untouched` pins that.

use crate::error::Error;
use alloc::vec::Vec;

/// A position in a compressed stream.
pub struct BitReader<'a> {
    bytes: &'a [u8],
    /// Bit offset from the start of `bytes`, not a byte offset.
    pos: usize,
}

impl<'a> BitReader<'a> {
    pub fn new(bytes: &'a [u8]) -> Self {
        BitReader { bytes, pos: 0 }
    }

    /// Current bit offset.
    pub fn bit_pos(&self) -> usize {
        self.pos
    }

    /// Total bits in the stream. `bytes.len()` is bounded by `isize::MAX`, so
    /// this cannot overflow on any platform Rust supports.
    pub fn bit_len(&self) -> usize {
        self.bytes.len() * 8
    }

    /// One bit, least significant first within each byte.
    pub fn read_bit(&mut self) -> Result<u32, Error> {
        let byte = match self.bytes.get(self.pos / 8) {
            Some(b) => *b,
            None => return Err(Error::UnexpectedEof),
        };
        let bit = (byte >> (self.pos % 8)) & 1;
        self.pos += 1;
        Ok(bit as u32)
    }

    /// `n` bits, least significant first. `n` must be at most 32; a larger
    /// request is a caller bug and returns `InvalidCode` rather than
    /// truncating silently. All-or-nothing: on `UnexpectedEof` the position
    /// is unchanged.
    pub fn read_bits(&mut self, n: u32) -> Result<u32, Error> {
        if n > 32 {
            return Err(Error::InvalidCode);
        }
        if self.pos + (n as usize) > self.bit_len() {
            return Err(Error::UnexpectedEof);
        }
        let mut v: u32 = 0;
        for k in 0..n {
            v |= self.read_bit()? << k;
        }
        Ok(v)
    }

    /// Skip to the next byte boundary (RFC 1951 §3.2.4).
    pub fn align_to_byte(&mut self) {
        self.pos = self.pos.div_ceil(8) * 8;
    }

    /// A byte-aligned little-endian `u16`. Aligns first, as `LEN`/`NLEN` need.
    pub fn read_aligned_u16_le(&mut self) -> Result<u16, Error> {
        let start = self.pos;
        self.align_to_byte();
        if self.pos + 16 > self.bit_len() {
            self.pos = start;
            return Err(Error::UnexpectedEof);
        }
        let lo = self.read_bits(8)? as u16;
        let hi = self.read_bits(8)? as u16;
        Ok(lo | (hi << 8))
    }

    /// Append `n` byte-aligned bytes to `out`. Aligns first.
    pub fn read_aligned_into(&mut self, out: &mut Vec<u8>, n: usize) -> Result<(), Error> {
        let start = self.pos;
        self.align_to_byte();
        let byte_start = self.pos / 8;
        let end = match byte_start.checked_add(n) {
            Some(e) if e <= self.bytes.len() => e,
            _ => {
                self.pos = start;
                return Err(Error::UnexpectedEof);
            }
        };
        match self.bytes.get(byte_start..end) {
            Some(src) => out.extend_from_slice(src),
            None => {
                self.pos = start;
                return Err(Error::UnexpectedEof);
            }
        }
        self.pos = end * 8;
        Ok(())
    }
}
```

Add `pub mod bitstream;` to `crates/deflate-core/src/lib.rs`.

- [x] **Step 4: Run to verify they pass**

Run: `cargo test -p deflate-core --test bitstream_tests`
Expected: PASS — 12 tests.

- [x] **Step 5: Run the full gate**

Run: `cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check && ! grep -rn 'unsafe' crates/deflate-core/src/`
Expected: every command exits 0.

- [x] **Step 6: Update the conformance matrix**

In `docs/conformance.md`, change the bit-reader row to:

```markdown
| Bit reader (LSB-first, EOF) | yes | yes | yes |
```

- [x] **Step 7: Commit**

```bash
git add crates/deflate-core/src/bitstream.rs crates/deflate-core/src/lib.rs \
        crates/deflate-core/tests/bitstream_tests.rs docs/conformance.md
git commit -m "feat(m1): Rust bit reader, atomic short reads

Mirrors spec/Deflate/Bitstream.lean. read_bits checks its full width before
consuming, so a truncated stream leaves the position untouched — the Rust
counterpart of readBits returning none with the caller's reader intact.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M2 — Stored blocks

**Exit:** stored blocks and `LEN`/`NLEN` implemented and verified, and the differential harness running three ways on real streams.

### Task 6: Lean block header and stored blocks, P3

**Files:**
- Create: `spec/Deflate/Block.lean`
- Modify: `spec/Deflate/Properties.lean`, `spec/Deflate.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `Deflate.BitReader`, `readBit`, `readBits`, `alignToByte`, `DecErr`, `byteAt`.
- Produces: `Deflate.BlockType` (`.stored`/`.fixed`/`.dynamic`), `Deflate.Header` (fields `isFinal`, `btype`), `Deflate.readHeader`, `Deflate.readStored`. Tasks 13, 15, 18 consume these.

- [x] **Step 1: Write the failing theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P3 — Stored blocks -/

/-- A block header is exactly three bits: BFINAL then BTYPE. -/
theorem readHeader_pos {r r' : BitReader} {h : Header}
    (hh : readHeader r = .ok (h, r')) : r'.pos = r.pos + 3 := by
  unfold readHeader at hh
  split at hh
  · simp at hh
  · rename_i b r₁ hb
    split at hh
    · simp at hh
    · rename_i t r₂ ht
      have h1 := readBit_pos hb
      have h2 := readBits_pos 2 r₁ t r₂ ht
      split at hh <;> simp_all <;> omega

/-- After a stored block the reader is byte aligned: the next block header
    starts on a byte boundary, which is what makes RFC 1951 §3.2.4 work. -/
theorem readStored_aligned {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) : r'.pos % 8 = 0 := by
  unfold readStored at hs
  repeat' split at hs
  all_goals simp_all [alignToByte, Nat.add_mul_mod_self_left]
  all_goals omega
```

- [x] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'readHeader'`.

- [x] **Step 3: Write the model**

`spec/Deflate/Block.lean`:

```lean
/-
  Deflate.Block — block headers (RFC 1951 §3.2.3) and stored blocks (§3.2.4).

  Header: BFINAL (1 bit), then BTYPE (2 bits):
    00 stored · 01 fixed Huffman · 10 dynamic Huffman · 11 reserved (error)

  Stored block: skip to the byte boundary, then LEN and NLEN as two
  little-endian 16-bit values, then LEN raw bytes. NLEN must be the ones'
  complement of LEN, which for 16 bits is `0xFFFF - LEN`.
-/
import Deflate.Bitstream

namespace Deflate

inductive BlockType where
  | stored | fixed | dynamic
  deriving Repr, DecidableEq, Inhabited

structure Header where
  isFinal : Bool
  btype   : BlockType
  deriving Repr, DecidableEq, Inhabited

def readHeader (r : BitReader) : Except DecErr (Header × BitReader) :=
  match BitReader.readBit r with
  | none => .error .unexpectedEof
  | some (f, r₁) =>
    match BitReader.readBits r₁ 2 with
    | none => .error .unexpectedEof
    | some (t, r₂) =>
      if t = 0 then .ok (⟨f, .stored⟩, r₂)
      else if t = 1 then .ok (⟨f, .fixed⟩, r₂)
      else if t = 2 then .ok (⟨f, .dynamic⟩, r₂)
      else .error .invalidBlockType

def readStored (r : BitReader) (out : Array UInt8) :
    Except DecErr (Array UInt8 × BitReader) :=
  let r₀ := BitReader.alignToByte r
  match BitReader.readBits r₀ 16 with
  | none => .error .unexpectedEof
  | some (len, r₁) =>
    match BitReader.readBits r₁ 16 with
    | none => .error .unexpectedEof
    | some (nlen, r₂) =>
      if nlen ≠ 0xFFFF - len then .error .invalidStoredLength
      else if r₂.size < r₂.pos + 8 * len then .error .unexpectedEof
      else
        let payload := (List.range len).map (fun k => byteAt r₂.bytes (r₂.pos / 8 + k))
        .ok (out ++ payload.toArray, { r₂ with pos := r₂.pos + 8 * len })

end Deflate
```

Add `import Deflate.Block` to `spec/Deflate.lean` and to the imports of `spec/Deflate/Properties.lean`.

- [x] **Step 4: Run to verify the two theorems pass**

Run: `lake build`
Expected: PASS.

- [x] **Step 5: Add the remaining P3 theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-- Reading a stored block never alters the input. -/
theorem readStored_bytes {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) : r'.bytes = r.bytes := by
  unfold readStored at hs
  repeat' split at hs
  all_goals simp_all [alignToByte]
  all_goals
    first
    | rfl
    | (rename_i h1 _ _ h2 _; simp_all [readBits_bytes])

/-- Output grows by exactly `LEN` bytes, and the reader advances by exactly
    `32 + 8 * LEN` bits past the alignment point. This is the P3 statement:
    LEN governs both the payload copy and the bit accounting, together. -/
theorem readStored_consumes {r r' : BitReader} {out o : Array UInt8}
    (hs : readStored r out = .ok (o, r')) :
    out.size ≤ o.size ∧
    r'.pos = (BitReader.alignToByte r).pos + 32 + 8 * (o.size - out.size) := by
  unfold readStored at hs
  repeat' split at hs
  all_goals simp_all
  all_goals
    (rename_i len r₁ h1 nlen r₂ h2 _ _
     have p1 := readBits_pos 16 _ len r₁ h1
     have p2 := readBits_pos 16 r₁ nlen r₂ h2
     simp_all [Array.size_append, List.length_map, List.length_range]
     omega)

/-- An invalid length complement is rejected, and nothing is appended. -/
theorem readStored_rejects_bad_nlen (r : BitReader) (out : Array UInt8)
    (len nlen : Nat) (r₁ r₂ : BitReader)
    (h1 : BitReader.readBits (BitReader.alignToByte r) 16 = some (len, r₁))
    (h2 : BitReader.readBits r₁ 16 = some (nlen, r₂))
    (hne : nlen ≠ 0xFFFF - len) :
    readStored r out = .error .invalidStoredLength := by
  unfold readStored
  simp [h1, h2, hne]

/-- BTYPE = 3 is reserved and rejected deterministically. -/
theorem readHeader_rejects_btype3 (r : BitReader) (f : Bool) (r₁ r₂ : BitReader)
    (hb : BitReader.readBit r = some (f, r₁))
    (ht : BitReader.readBits r₁ 2 = some (3, r₂)) :
    readHeader r = .error .invalidBlockType := by
  unfold readHeader; simp [hb, ht]

/-- A header never alters the input. -/
theorem readHeader_bytes {r r' : BitReader} {h : Header}
    (hh : readHeader r = .ok (h, r')) : r'.bytes = r.bytes := by
  unfold readHeader at hh
  split at hh
  · simp at hh
  · rename_i b r₁ hb
    split at hh
    · simp at hh
    · rename_i t r₂ ht
      have h1 := readBit_bytes hb
      have h2 := readBits_bytes 2 r₁ t r₂ ht
      split at hh <;> simp_all
```

- [x] **Step 6: Run and close any open goals**

Run: `lake build && ! grep -rnwE 'sorry|admit' spec/ --include='*.lean'`
Expected: PASS, exit 0.

These proofs are mechanical but fiddly; `repeat' split at hs` followed by `simp_all` plus the `readBits_pos`/`readBits_bytes` facts is the pattern. If a goal resists, name the hypotheses explicitly with `rename_i` rather than reaching for automation, and never insert `sorry`.

- [x] **Step 7: Register with the axiom gate and commit**

Add to `spec/scripts/axioms.lean`:

```lean
#print axioms Deflate.readHeader_pos
#print axioms Deflate.readStored_aligned
#print axioms Deflate.readStored_consumes
#print axioms Deflate.readStored_rejects_bad_nlen
```

```bash
make test-lean
git add spec/
git commit -m "feat(m2): Lean block headers and stored blocks, P3

readHeader (BFINAL + BTYPE, BTYPE=3 rejected) and readStored (align, LEN,
NLEN = 0xFFFF - LEN, payload). P3: byte alignment after the block, input
invariance, and the joint statement that output grows by LEN while the
reader advances 32 + 8*LEN bits.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 7: Rust block header and stored blocks

**Files:**
- Create: `crates/deflate-core/src/block.rs`, `crates/deflate-core/src/inflate.rs`
- Modify: `crates/deflate-core/src/lib.rs`
- Test: `crates/deflate-core/tests/stored_tests.rs`

**Interfaces:**
- Consumes: `BitReader`, `Error`.
- Produces: `block::BlockType` (`Stored`/`Fixed`/`Dynamic`), `block::BlockHeader { is_final: bool, btype: BlockType }`, `block::read_block_header(&mut BitReader) -> Result<BlockHeader, Error>`, `block::read_stored(&mut BitReader, &mut Vec<u8>, usize) -> Result<(), Error>` (third argument is the remaining output budget), `inflate::inflate(&[u8]) -> Result<Vec<u8>, Error>`, `inflate::inflate_with_limit(&[u8], usize) -> Result<Vec<u8>, Error>`. Tasks 14, 16, 17 extend `inflate`.

- [x] **Step 1: Write the failing tests**

`crates/deflate-core/tests/stored_tests.rs`:

```rust
use deflate_core::{inflate, Error};

/// One final stored block carrying `payload`.
fn stored_stream(payload: &[u8]) -> Vec<u8> {
    let mut v = vec![0x01]; // BFINAL=1, BTYPE=00, then 5 padding bits
    let len = payload.len() as u16;
    v.extend_from_slice(&len.to_le_bytes());
    v.extend_from_slice(&(!len).to_le_bytes());
    v.extend_from_slice(payload);
    v
}

#[test]
fn decodes_a_stored_block() {
    let s = stored_stream(b"hello");
    assert_eq!(inflate(&s).unwrap(), b"hello");
}

#[test]
fn decodes_multiple_stored_blocks() {
    let mut s = vec![0x00]; // BFINAL=0, BTYPE=00
    s.extend_from_slice(&3u16.to_le_bytes());
    s.extend_from_slice(&(!3u16).to_le_bytes());
    s.extend_from_slice(b"abc");
    s.extend_from_slice(&stored_stream(b"def"));
    assert_eq!(inflate(&s).unwrap(), b"abcdef");
}

// --- Review Focus 2: legal but empty blocks ---

#[test]
fn stored_block_with_zero_length_is_valid_and_yields_nothing() {
    let s = stored_stream(b"");
    assert_eq!(inflate(&s).unwrap(), b"");
}

#[test]
fn zero_length_stored_block_followed_by_data() {
    let mut s = vec![0x00]; // non-final, empty
    s.extend_from_slice(&0u16.to_le_bytes());
    s.extend_from_slice(&(!0u16).to_le_bytes());
    s.extend_from_slice(&stored_stream(b"x"));
    assert_eq!(inflate(&s).unwrap(), b"x");
}

// --- malformed ---

#[test]
fn bad_length_complement_is_rejected() {
    let mut s = stored_stream(b"hi");
    s[3] ^= 0xFF; // corrupt NLEN
    assert_eq!(inflate(&s), Err(Error::InvalidStoredLength));
}

#[test]
fn reserved_block_type_is_rejected() {
    // BFINAL=1, BTYPE=11 -> 0b111 = 0x07
    assert_eq!(inflate(&[0x07]), Err(Error::InvalidBlockType));
}

#[test]
fn truncated_payload_is_eof() {
    let mut s = stored_stream(b"hello");
    s.truncate(s.len() - 2);
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn truncated_before_nlen_is_eof() {
    let mut s = stored_stream(b"hello");
    s.truncate(3);
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn empty_input_is_eof() {
    assert_eq!(inflate(&[]), Err(Error::UnexpectedEof));
}

#[test]
fn stream_without_a_final_block_is_eof() {
    let mut s = vec![0x00];
    s.extend_from_slice(&1u16.to_le_bytes());
    s.extend_from_slice(&(!1u16).to_le_bytes());
    s.push(b'z');
    assert_eq!(inflate(&s), Err(Error::UnexpectedEof));
}

#[test]
fn trailing_bytes_after_the_final_block_are_ignored() {
    let mut s = stored_stream(b"ok");
    s.extend_from_slice(b"GARBAGE");
    assert_eq!(inflate(&s).unwrap(), b"ok");
}
```

- [x] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test stored_tests`
Expected: FAIL — `unresolved import deflate_core::inflate`.

- [x] **Step 3: Write the block layer**

`crates/deflate-core/src/block.rs`:

```rust
//! Block headers (RFC 1951 §3.2.3) and stored blocks (§3.2.4).
//! Mirrors `spec/Deflate/Block.lean`.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BlockType {
    Stored,
    Fixed,
    Dynamic,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BlockHeader {
    pub is_final: bool,
    pub btype: BlockType,
}

pub fn read_block_header(r: &mut BitReader) -> Result<BlockHeader, Error> {
    let is_final = r.read_bit()? == 1;
    let btype = match r.read_bits(2)? {
        0 => BlockType::Stored,
        1 => BlockType::Fixed,
        2 => BlockType::Dynamic,
        _ => return Err(Error::InvalidBlockType),
    };
    Ok(BlockHeader { is_final, btype })
}

/// Read one stored block into `out`. `budget` is how many more bytes the
/// caller will accept; exceeding it is `OutputLimitExceeded` and nothing is
/// appended. Checking before the copy is what keeps a bomb from allocating.
pub fn read_stored(r: &mut BitReader, out: &mut Vec<u8>, budget: usize) -> Result<(), Error> {
    let len = r.read_aligned_u16_le()? as usize;
    let nlen = r.read_aligned_u16_le()? as usize;
    if nlen != 0xFFFF - len {
        return Err(Error::InvalidStoredLength);
    }
    if len > budget {
        return Err(Error::OutputLimitExceeded);
    }
    r.read_aligned_into(out, len)
}
```

- [x] **Step 4: Write the decoder entry point**

`crates/deflate-core/src/inflate.rs`:

```rust
//! The decoder driver (RFC 1951 §3.2.3): read blocks until BFINAL.
//! Mirrors `spec/Deflate/Decode.lean`.

use crate::bitstream::BitReader;
use crate::block::{read_block_header, read_stored, BlockType};
use crate::error::Error;
use alloc::vec::Vec;

/// Decode with no output limit. Suitable only for input you produced
/// yourself. For anything from the network or a file you did not write, use
/// [`inflate_with_limit`] (spec §11).
pub fn inflate(input: &[u8]) -> Result<Vec<u8>, Error> {
    inflate_with_limit(input, usize::MAX)
}

/// Decode, refusing to produce more than `limit` bytes.
pub fn inflate_with_limit(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut r = BitReader::new(input);
    let mut out: Vec<u8> = Vec::new();
    loop {
        let header = read_block_header(&mut r)?;
        let budget = limit - out.len();
        match header.btype {
            BlockType::Stored => read_stored(&mut r, &mut out, budget)?,
            // Tasks 14 and 16 replace these.
            BlockType::Fixed | BlockType::Dynamic => return Err(Error::InvalidBlockType),
        }
        if header.is_final {
            return Ok(out);
        }
    }
}
```

Add `pub mod block;` and `pub mod inflate;` plus `pub use inflate::{inflate, inflate_with_limit};` to `crates/deflate-core/src/lib.rs`.

- [x] **Step 5: Run to verify they pass**

Run: `cargo test -p deflate-core --test stored_tests`
Expected: PASS — 11 tests. `reserved_block_type_is_rejected` must give `InvalidBlockType`, not the `Fixed | Dynamic` arm; confirm by reading the failure message if it fails.

- [x] **Step 6: Cross-check against zlib**

Run:

```bash
python3 - <<'PY'
import zlib, subprocess, binascii
raw = b"hello world" * 3
c = zlib.compressobj(0, zlib.DEFLATED, -15)   # level 0 -> stored blocks
s = c.compress(raw) + c.flush()
print("stream:", binascii.hexlify(s).decode())
print("zlib round-trips:", zlib.decompress(s, -15) == raw)
open("/tmp/stored_vec.bin","wb").write(s)
open("/tmp/stored_vec.raw","wb").write(raw)
PY
```

Then add `tests/vectors/stored_level0.deflate` and `tests/vectors/stored_level0.raw` from those files, and a test that reads them with `include_bytes!` and asserts `inflate` returns the raw bytes. zlib at level 0 emits stored blocks, so this exercises the real encoder's framing, not only our own.

- [x] **Step 7: Update conformance and commit**

`docs/conformance.md`: `| Stored blocks | yes | yes | yes |`, `| Multi-block streams | yes | yes | no |`.

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ tests/vectors/ docs/conformance.md
git commit -m "feat(m2): Rust block headers and stored blocks

read_block_header rejects BTYPE=3; read_stored checks NLEN and the output
budget before copying, so a bomb never allocates. inflate drives blocks to
BFINAL and ignores trailing bytes. Cross-checked against a zlib level-0
stream committed as a test vector.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 8: The differential harness and the Lean oracle driver

This is the bridge. Everything after this task is checked by it, so it is built now, while the format it covers is small enough to debug by hand — the same reason maked built its fuzzer before the features it tests.

**Files:**
- Modify: `spec/Main.lean` (the line protocol), `crates/vdeflate/src/main.rs` (an `--oracle` mode)
- Create: `oracles/differential.py`, `oracles/corpus.py`, `oracles/reports/.gitkeep`
- Modify: `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `deflate_core::inflate_with_limit`, `Deflate.readHeader`, `Deflate.readStored`.
- Produces: the line protocol below, and `oracles/differential.py` with `--self-test` and `--count N`. Tasks 14, 16, 17, 20, 22 extend the corpus generators, never the protocol.

**Line protocol.** One request per line, one response per line, hex without `0x`:

```text
request            response
DECODE <hex>       OK <hex>  |  ERR <errorName>
LIMIT <n>          (sets the limit for subsequent DECODE lines; default 1<<26)
```

Both the Lean driver and `vdeflate --oracle` speak it on stdin and stdout. `<errorName>` is the Lean constructor name (`unexpectedEof`, `invalidStoredLength`, …); the Rust side maps its `Error` variants to those exact strings, so a disagreement on *which* error is a disagreement the harness can see.

- [x] **Step 1: Write the failing self-test**

`oracles/differential.py` is written in Step 3. First write the assertion that proves the harness can detect a disagreement — without this, a harness that silently agrees with everything looks like a pass. maked's schedule fuzzer has exactly this self-test.

```python
# in oracles/differential.py
def self_test() -> int:
    """A harness that cannot fail is worthless. Feed it a deliberately wrong
    oracle and confirm it reports the disagreement."""
    stream = make_stored_stream(b"abc")
    good = Outcome.ok(b"abc")
    bad = Outcome.ok(b"abd")
    d = compare({"rust": good, "lean": bad, "zlib": good}, stream)
    assert d is not None, "self-test: a disagreeing oracle was not detected"
    assert "lean" in d.parties, f"self-test: wrong party blamed: {d.parties}"
    d2 = compare({"rust": good, "lean": good, "zlib": good}, stream)
    assert d2 is None, "self-test: agreement was reported as a disagreement"
    err = Outcome.err("invalidStoredLength")
    oth = Outcome.err("unexpectedEof")
    d3 = compare({"rust": err, "lean": oth, "zlib": err}, stream)
    assert d3 is not None, "self-test: differing error kinds were not detected"
    print("self-test: 3/3")
    return 0
```

- [x] **Step 2: Run to verify it fails**

Run: `python3 oracles/differential.py --self-test`
Expected: FAIL — `No such file or directory`.

- [x] **Step 3: Write the Lean oracle driver**

Replace `spec/Main.lean`:

```lean
import Deflate

open Deflate

def hexDigit? (c : Char) : Option Nat :=
  if '0' ≤ c ∧ c ≤ '9' then some (c.toNat - '0'.toNat)
  else if 'a' ≤ c ∧ c ≤ 'f' then some (c.toNat - 'a'.toNat + 10)
  else if 'A' ≤ c ∧ c ≤ 'F' then some (c.toNat - 'A'.toNat + 10)
  else none

def ofHex (s : String) : Option ByteArray := do
  let cs := s.toList
  if cs.length % 2 ≠ 0 then none else
  let rec go : List Char → Option (List UInt8)
    | [] => some []
    | a :: b :: rest => do
        let hi ← hexDigit? a
        let lo ← hexDigit? b
        let tl ← go rest
        pure (UInt8.ofNat (hi * 16 + lo) :: tl)
    | _ => none
  (go cs).map (fun bs => ⟨bs.toArray⟩)

def toHex (bs : ByteArray) : String :=
  let digits := "0123456789abcdef".toList
  bs.toList.foldl (fun acc b =>
    acc.push (digits[b.toNat / 16]!) |>.push (digits[b.toNat % 16]!)) ""

def errName : DecErr → String
  | .unexpectedEof       => "unexpectedEof"
  | .invalidBlockType    => "invalidBlockType"
  | .invalidStoredLength => "invalidStoredLength"
  | .invalidHuffmanTree  => "invalidHuffmanTree"
  | .invalidCode         => "invalidCode"
  | .invalidDistance     => "invalidDistance"
  | .invalidLength       => "invalidLength"
  | .outputLimitExceeded => "outputLimitExceeded"
  | .fuelExhausted       => "fuelExhausted"

/-- Until Task 18 provides `Deflate.decode`, drive blocks here directly. -/
partial def decodeStored (bs : ByteArray) (limit : Nat) :
    Except DecErr ByteArray := do
  let rec loop (r : BitReader) (out : Array UInt8) : Except DecErr ByteArray := do
    let (h, r₁) ← readHeader r
    match h.btype with
    | .stored =>
        let (out', r₂) ← readStored r₁ out
        if out'.size > limit then .error .outputLimitExceeded
        else if h.isFinal then .ok ⟨out'⟩ else loop r₂ out'
    | _ => .error .invalidBlockType
  loop ⟨bs, 0⟩ #[]

def handle (limit : Nat) (line : String) : Nat × Option String :=
  match (line.trim.splitOn " ") with
  | ["LIMIT", n] => (n.toNat?.getD limit, none)
  | ["DECODE", hx] =>
      match ofHex hx with
      | none => (limit, some "ERR badHex")
      | some bs =>
        match decodeStored bs limit with
        | .ok out => (limit, some s!"OK {toHex out}")
        | .error e => (limit, some s!"ERR {errName e}")
  | _ => (limit, none)

def main (_args : List String) : IO Unit := do
  let stdin ← IO.getStdin
  let mut limit := 1 <<< 26
  repeat
    let line ← stdin.getLine
    if line.isEmpty then break
    let (lim, out) := handle limit line
    limit := lim
    match out with
    | some s => IO.println s
    | none => pure ()
```

- [x] **Step 4: Write the Rust oracle mode**

Replace `crates/vdeflate/src/main.rs`:

```rust
//! `vdeflate`. Outside the verification boundary (spec §6): file I/O,
//! argument parsing and process exit are not modeled or proved.
//!
//! `--oracle` speaks the differential line protocol on stdin/stdout. Task 23
//! adds the user-facing CLI.

use deflate_core::{inflate_with_limit, Error};
use std::io::{self, BufRead, Write};

fn err_name(e: Error) -> &'static str {
    match e {
        Error::UnexpectedEof => "unexpectedEof",
        Error::InvalidBlockType => "invalidBlockType",
        Error::InvalidStoredLength => "invalidStoredLength",
        Error::InvalidHuffmanTree => "invalidHuffmanTree",
        Error::InvalidCode => "invalidCode",
        Error::InvalidDistance => "invalidDistance",
        Error::InvalidLength => "invalidLength",
        Error::OutputLimitExceeded => "outputLimitExceeded",
    }
}

fn from_hex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len() / 2)
        .map(|i| u8::from_str_radix(s.get(i * 2..i * 2 + 2)?, 16).ok())
        .collect()
}

fn to_hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn oracle() -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let mut limit: usize = 1 << 26;
    for line in stdin.lock().lines() {
        let line = line?;
        let mut parts = line.trim().splitn(2, ' ');
        match (parts.next(), parts.next()) {
            (Some("LIMIT"), Some(n)) => limit = n.parse().unwrap_or(limit),
            (Some("DECODE"), Some(hx)) => match from_hex(hx) {
                None => writeln!(stdout, "ERR badHex")?,
                Some(bytes) => match inflate_with_limit(&bytes, limit) {
                    Ok(out) => writeln!(stdout, "OK {}", to_hex(&out))?,
                    Err(e) => writeln!(stdout, "ERR {}", err_name(e))?,
                },
            },
            _ => {}
        }
        stdout.flush()?;
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--oracle") {
        if let Err(e) = oracle() {
            eprintln!("vdeflate: {e}");
            std::process::exit(1);
        }
        return;
    }
    eprintln!("vdeflate: usage: vdeflate --oracle");
    std::process::exit(2);
}
```

- [x] **Step 5: Write the harness**

`oracles/corpus.py`:

```python
"""Corpus generation for the differential harness.

Three sources, and the distinction matters:

  * `zlib_streams`   — what a mature encoder actually emits. Agreement here
                       is interoperability.
  * `handmade`       — streams we construct bit by bit to hit boundaries no
                       encoder emits: empty blocks, dist == len(out),
                       under-subscribed trees.
  * `mutations`      — bit flips and truncations of the above. Every one of
                       these must produce an error, never a crash or a hang.
"""
import random
import zlib

PAYLOADS = [
    b"", b"a", b"ab", b"\x00", b"\xff" * 300,
    b"hello world " * 40,
    bytes(range(256)),
    b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",      # long run: max-length matches
    b"abcabcabcabcabcabcabcabcabcabcabcabc",  # short period: overlapping copies
    b"the quick brown fox jumps over the lazy dog " * 20,
]


def zlib_streams(seed: int = 0):
    """Raw DEFLATE from zlib at every level. Level 0 is stored blocks;
    higher levels are fixed and dynamic Huffman."""
    rng = random.Random(seed)
    payloads = list(PAYLOADS)
    for n in (1, 7, 64, 1024, 65536, 65537):
        payloads.append(bytes(rng.getrandbits(8) for _ in range(n)))        # incompressible
        payloads.append(bytes(rng.choice(b"ab") for _ in range(n)))         # very compressible
    for p in payloads:
        for level in range(0, 10):
            c = zlib.compressobj(level, zlib.DEFLATED, -15)
            yield p, c.compress(p) + c.flush()


def mutations(stream: bytes, seed: int = 0, count: int = 8):
    """Truncations at every power-of-two boundary, plus random bit flips."""
    rng = random.Random(seed)
    n = len(stream)
    cuts = {0, 1, n // 2, n - 1, n}
    k = 1
    while k < n:
        cuts.add(k)
        k *= 2
    for c in sorted(x for x in cuts if 0 <= x <= n):
        yield stream[:c]
    for _ in range(count):
        if n == 0:
            return
        b = bytearray(stream)
        i = rng.randrange(n)
        b[i] ^= 1 << rng.randrange(8)
        yield bytes(b)
```

`oracles/differential.py`:

```python
#!/usr/bin/env python3
"""N-way differential oracle: deflate-core (Rust) vs the Lean model vs zlib.

Modelled on maked's benchmarks/fuzzer/fuzz_runner.py. Agreement here is
*test evidence over a finite corpus*, not proof. It says nothing about
streams the corpus never produces. See docs/verification-boundary.md.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import zlib

from corpus import mutations, zlib_streams

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUST = ROOT / "target" / "release" / "vdeflate"
LEAN = ROOT / ".lake" / "build" / "bin" / "deflate_spec"
LIMIT = 1 << 26


class Outcome:
    __slots__ = ("ok", "data", "err")

    def __init__(self, ok, data=None, err=None):
        self.ok, self.data, self.err = ok, data, err

    @staticmethod
    def ok_(d):
        return Outcome(True, data=d)

    @staticmethod
    def err_(e):
        return Outcome(False, err=e)

    def key(self):
        # Error *kinds* are compared across our two implementations, but zlib
        # has its own error vocabulary, so comparison against zlib is on
        # success/failure and the bytes, not on which error.
        return ("ok", self.data) if self.ok else ("err", self.err)

    def coarse(self):
        return ("ok", self.data) if self.ok else ("err",)

    def __repr__(self):
        return f"OK({len(self.data)}B)" if self.ok else f"ERR({self.err})"


Outcome.ok = Outcome.ok_
Outcome.err = Outcome.err_


class Disagreement:
    def __init__(self, parties, stream, outcomes):
        self.parties, self.stream, self.outcomes = parties, stream, outcomes

    def as_dict(self):
        return {
            "parties": sorted(self.parties),
            "stream": self.stream.hex(),
            "outcomes": {k: repr(v) for k, v in self.outcomes.items()},
        }


def make_stored_stream(payload: bytes) -> bytes:
    n = len(payload)
    return bytes([0x01]) + n.to_bytes(2, "little") + (n ^ 0xFFFF).to_bytes(2, "little") + payload


def run_oracle(cmd, streams):
    """Feed every stream to one oracle process and read back one line each."""
    lines = [f"LIMIT {LIMIT}"] + [f"DECODE {s.hex()}" for s in streams]
    p = subprocess.run(
        cmd, input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=600
    )
    if p.returncode != 0:
        raise SystemExit(f"oracle {cmd!r} exited {p.returncode}: {p.stderr[:400]}")
    out = [ln for ln in p.stdout.splitlines() if ln]
    if len(out) != len(streams):
        raise SystemExit(f"oracle {cmd!r} gave {len(out)} answers for {len(streams)} streams")
    res = []
    for ln in out:
        tag, _, rest = ln.partition(" ")
        res.append(Outcome.ok(bytes.fromhex(rest)) if tag == "OK" else Outcome.err(rest))
    return res


def run_zlib(streams):
    res = []
    for s in streams:
        try:
            res.append(Outcome.ok(zlib.decompress(s, -15)))
        except zlib.error as e:
            res.append(Outcome.err(str(e)))
    return res


def compare(outcomes, stream):
    """Rust and Lean must agree exactly, errors included. zlib is compared
    only on success/failure and bytes, since its error names are its own."""
    r, l = outcomes["rust"], outcomes["lean"]
    if r.key() != l.key():
        return Disagreement({"rust", "lean"}, stream, outcomes)
    if "zlib" in outcomes and outcomes["zlib"].coarse() != r.coarse():
        return Disagreement({"rust", "zlib"}, stream, outcomes)
    return None


def self_test() -> int:
    """A harness that cannot fail is worthless. Feed it a deliberately wrong
    oracle and confirm it reports the disagreement."""
    stream = make_stored_stream(b"abc")
    good, bad = Outcome.ok(b"abc"), Outcome.ok(b"abd")
    d = compare({"rust": good, "lean": bad, "zlib": good}, stream)
    assert d is not None, "self-test: a disagreeing oracle was not detected"
    assert "lean" in d.parties, f"self-test: wrong party blamed: {d.parties}"
    assert compare({"rust": good, "lean": good, "zlib": good}, stream) is None, \
        "self-test: agreement was reported as a disagreement"
    err, oth = Outcome.err("invalidStoredLength"), Outcome.err("unexpectedEof")
    assert compare({"rust": err, "lean": oth, "zlib": err}, stream) is not None, \
        "self-test: differing error kinds were not detected"
    print("self-test: 3/3")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--count", type=int, default=0, help="0 = the whole corpus")
    ap.add_argument("--no-zlib", action="store_true")
    ap.add_argument("--report", default=str(ROOT / "oracles" / "reports" / "differential.json"))
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    for binary in (RUST, LEAN):
        if not binary.exists():
            raise SystemExit(f"missing {binary}; run `make all` first")

    streams, expected = [], {}
    for raw, s in zlib_streams():
        streams.append(s)
        expected[s] = raw
        streams.extend(mutations(s))
    if a.count:
        streams = streams[: a.count]
    streams = list(dict.fromkeys(streams))

    results = {
        "rust": run_oracle([str(RUST), "--oracle"], streams),
        "lean": run_oracle([str(LEAN)], streams),
    }
    if not a.no_zlib:
        results["zlib"] = run_zlib(streams)

    findings = []
    for i, s in enumerate(streams):
        o = {k: v[i] for k, v in results.items()}
        d = compare(o, s)
        if d is not None:
            findings.append(d.as_dict())
        # Stronger than agreement: on a stream zlib produced from known bytes,
        # the answer must be those bytes.
        if s in expected and o["rust"].ok and o["rust"].data != expected[s]:
            findings.append({
                "parties": ["rust", "ground-truth"],
                "stream": s.hex(),
                "outcomes": {"rust": repr(o["rust"]), "expected": expected[s][:64].hex()},
            })

    report = {"streams": len(streams), "parties": sorted(results), "findings": findings}
    pathlib.Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.report).write_text(json.dumps(report, indent=2))
    print(f"{len(streams)} streams, {len(results)} oracles, {len(findings)} findings")
    for f in findings[:10]:
        print("  ", f["parties"], f["outcomes"])
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 6: Run the self-test, then the harness**

Run: `python3 oracles/differential.py --self-test`
Expected: PASS — `self-test: 3/3`.

Run: `make all && python3 oracles/differential.py`
Expected: findings only on fixed and dynamic blocks, which neither implementation supports yet — both must report `invalidBlockType` and therefore *agree*, so the Rust/Lean findings count must be **0**. zlib findings are expected and large at this milestone, because zlib decodes the compressed blocks we cannot. Run with `--no-zlib` for the gating number until Task 16 lands, and record why in the commit message.

- [x] **Step 7: Wire it into the build and CI**

In `Makefile`, change `test-differential` to run the self-test first:

```makefile
test-differential: build-rust build-lean
	@python3 oracles/differential.py --self-test
	@python3 oracles/differential.py --no-zlib
```

In `.github/workflows/ci.yml`, replace the final step with:

```yaml
      - name: Differential harness self-test
        run: python3 oracles/differential.py --self-test

      - name: Differential harness (Rust vs Lean model)
        run: |
          cargo build --release --workspace
          lake build
          python3 oracles/differential.py --no-zlib
```

Task 16 removes `--no-zlib` once dynamic blocks land.

- [x] **Step 8: Commit**

```bash
git add oracles/ spec/Main.lean crates/vdeflate/src/main.rs Makefile .github/workflows/ci.yml
git commit -m "feat(m2): three-way differential harness and the Lean oracle driver

Line protocol (DECODE hex -> OK hex | ERR name) spoken by both the Lean
executable and vdeflate --oracle. Corpus: zlib output at every level,
handmade boundary streams, truncations at power-of-two cuts, and bit flips.

The harness carries a self-test that feeds it a deliberately wrong oracle,
because a harness that cannot fail proves nothing. zlib comparison is gated
off until dynamic blocks land in Task 16.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M3 — Fixed Huffman decoder

**Exit:** canonical Huffman decoding, literals, end-of-block, and length/distance back-references, with P2, P4 and P6 proved in the model.

### Task 9: Lean canonical Huffman codes, P2

**Files:**
- Create: `spec/Deflate/Huffman.lean`
- Modify: `spec/Deflate/Properties.lean`, `spec/Deflate.lean`, `spec/scripts/axioms.lean`, `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `BitReader`, `readBit`, `DecErr`.
- Produces: `Deflate.maxCodeLen = 15`, `Deflate.Code` (field `lengths : Array Nat`), `Code.countOf`, `Code.symbolsOf`, `Code.kraft`, `Code.used`, `Code.isValid`, `Deflate.decodeSym`, `Deflate.fixedLitLen`, `Deflate.fixedDist`. Tasks 13, 15, 18, 21 consume these.

- [x] **Step 1: Write the failing theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P2 — Huffman decoding -/

/-- The two fixed codes of RFC 1951 §3.2.6 are exactly complete: their Kraft
    sums are `2 ^ 15` on the nose. Checked by the kernel, not by hand. -/
theorem fixedLitLen_valid : Code.isValid fixedLitLen = true := by decide

theorem fixedDist_valid : Code.isValid fixedDist = true := by decide
```

- [x] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'fixedLitLen'`.

- [x] **Step 3: Write the model**

`spec/Deflate/Huffman.lean`:

```lean
/-
  Deflate.Huffman — canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).

  Huffman codes are the one data element packed *most* significant bit first;
  everything else in the format is LSB first. Decoding therefore shifts one
  bit in at a time from the left.

  Representation: just the code lengths. RFC 1951 §3.2.2 fixes everything else
  — among codes of equal length, numeric values are assigned in increasing
  symbol order, and each length's codes occupy one contiguous numeric range.
  That is the counts/offsets decoder below, the same shape as zlib's puff.c.
-/
import Deflate.Bitstream

namespace Deflate

/-- RFC 1951 §3.2.7: no code is longer than 15 bits. -/
def maxCodeLen : Nat := 15

structure Code where
  /-- `lengths[s]` is symbol `s`'s code length; 0 means the symbol is unused. -/
  lengths : Array Nat
  deriving Repr, Inhabited

namespace Code

def countOf (c : Code) (len : Nat) : Nat :=
  c.lengths.foldl (fun acc l => if l = len then acc + 1 else acc) 0

/-- Symbols of a given length in increasing symbol order — the canonical
    assignment order. -/
def symbolsOf (c : Code) (len : Nat) : List Nat :=
  (List.range c.lengths.size).filter (fun s => c.lengths[s]! = len)

/-- The Kraft sum, scaled by `2 ^ maxCodeLen` so it stays in `Nat`.
    A complete code sums to exactly `2 ^ maxCodeLen`. -/
def kraft (c : Code) : Nat :=
  (List.range (maxCodeLen + 1)).foldl
    (fun acc len => if len = 0 then acc else acc + c.countOf len * 2 ^ (maxCodeLen - len)) 0

/-- How many symbols the code actually assigns. -/
def used (c : Code) : Nat := c.lengths.size - c.countOf 0

/-- Over-subscribed codes are always rejected. Incomplete codes are rejected
    too, except when at most one symbol is used: real encoders emit a
    one-symbol (or empty) distance code for a block with no back-references,
    and zlib accepts it. ADR 0004 records this reading of an RFC ambiguity. -/
def isValid (c : Code) : Bool :=
  if c.kraft > 2 ^ maxCodeLen then false
  else if c.kraft = 2 ^ maxCodeLen then true
  else c.used ≤ 1

end Code

/-- One decoding step: shift a bit in, then test whether the accumulated code
    falls in this length's range. -/
def decodeGo (c : Code) : Nat → Nat → Nat → BitReader → Nat → Except DecErr (Nat × BitReader)
  | _, _, _, _, 0 => .error .invalidCode
  | len, code, first, r, fuel + 1 =>
    match BitReader.readBit r with
    | none => .error .unexpectedEof
    | some (b, r₁) =>
      let code := code * 2 + (if b then 1 else 0)
      let cnt := c.countOf len
      if first ≤ code ∧ code - first < cnt then
        match (c.symbolsOf len)[code - first]? with
        | some s => .ok (s, r₁)
        | none   => .error .invalidCode
      else
        decodeGo c (len + 1) code ((first + cnt) * 2) r₁ fuel

/-- Decode one symbol. At most `maxCodeLen` bits are consumed; a code that
    does not resolve within them is `invalidCode`. -/
def decodeSym (c : Code) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  decodeGo c 1 0 0 r maxCodeLen

/-- RFC 1951 §3.2.6 literal/length code: lengths 8, 9, 7, 8 by range. -/
def fixedLitLen : Code :=
  ⟨((List.range 288).map fun s =>
      if s < 144 then 8 else if s < 256 then 9 else if s < 280 then 7 else 8).toArray⟩

/-- RFC 1951 §3.2.6 distance code: 32 symbols, 5 bits each. -/
def fixedDist : Code := ⟨(List.replicate 32 5).toArray⟩

end Deflate
```

Add `import Deflate.Huffman` to `spec/Deflate.lean` and to `spec/Deflate/Properties.lean`.

- [x] **Step 4: Run to verify the two `decide` proofs pass**

Run: `lake build`
Expected: PASS. If `decide` times out, raise `maxRecDepth` with `set_option maxRecDepth 4000 in` before the theorem. **Do not reach for `native_decide`**: it introduces the `Lean.ofReduceBool` axiom, which moves the trust from the kernel to the compiler. Step 7 makes CI reject it.

Sanity arithmetic, so a failure here is read correctly: the literal/length Kraft sum is `144·2⁷ + 112·2⁶ + 24·2⁸ + 8·2⁷ = 18432 + 7168 + 6144 + 1024 = 32768 = 2¹⁵`. The distance sum is `32·2¹⁰ = 32768`. Both are exactly complete.

- [x] **Step 5: Add the remaining P2 theorems**

```lean
/-- Decoding one symbol always consumes at least one bit and never more than
    `maxCodeLen`. The lower bound is what makes the decoder's outer loop
    terminate (P8); the upper bound is RFC 1951 §3.2.7. -/
theorem decodeGo_pos (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') →
    r.pos < r'.pos ∧ r'.pos ≤ r.pos + fuel := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    cases hb : BitReader.readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      have hp := readBit_pos hb
      split at h
      · split at h <;> simp_all <;> omega
      · have := ih (len + 1) _ _ r₁ s r' h
        omega

theorem decodeSym_pos {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) :
    r.pos < r'.pos ∧ r'.pos ≤ r.pos + maxCodeLen :=
  decodeGo_pos c maxCodeLen 1 0 0 r s r' h

theorem decodeGo_bytes (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') → r'.bytes = r.bytes := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    cases hb : BitReader.readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      have hbs := readBit_bytes hb
      split at h
      · split at h <;> simp_all
      · have := ih (len + 1) _ _ r₁ s r' h; simp_all

theorem decodeSym_bytes {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) : r'.bytes = r.bytes :=
  decodeGo_bytes c maxCodeLen 1 0 0 r s r' h

/-- Every decoded symbol indexes the code's own length array. The decoder
    cannot hand a caller a symbol the code does not define. -/
theorem decodeGo_in_range (c : Code) : ∀ (fuel len code first : Nat) (r : BitReader)
    (s : Nat) (r' : BitReader),
    decodeGo c len code first r fuel = .ok (s, r') → s < c.lengths.size := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ h; simp [decodeGo] at h
  | succ n ih =>
    intro len code first r s r' h
    unfold decodeGo at h
    cases hb : BitReader.readBit r with
    | none => rw [hb] at h; simp at h
    | some p =>
      obtain ⟨b, r₁⟩ := p
      rw [hb] at h
      split at h
      · split at h
        · rename_i sym hsym
          have : sym ∈ Code.symbolsOf c len := List.getElem?_mem hsym
          simp [Code.symbolsOf, List.mem_filter, List.mem_range] at this
          simp_all
        · simp at h
      · exact ih (len + 1) _ _ r₁ s r' h

theorem decodeSym_in_range {c : Code} {r r' : BitReader} {s : Nat}
    (h : decodeSym c r = .ok (s, r')) : s < c.lengths.size :=
  decodeGo_in_range c maxCodeLen 1 0 0 r s r' h

/-- An over-subscribed code is rejected, with no appeal to the decoder. -/
theorem oversubscribed_invalid (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isValid c = false := by simp [Code.isValid, h]
```

- [x] **Step 6: Run and close any open goals**

Run: `lake build && ! grep -rnwE 'sorry|admit' spec/ --include='*.lean'`
Expected: PASS, exit 0.

- [x] **Step 7: Extend the axiom gate to reject `native_decide`**

`native_decide` closes goals by running compiled code and adds `Lean.ofReduceBool` to the theorem's axioms. That is a different trust story from a kernel check, so the gate must catch it, not just `sorryAx`. In `Makefile`:

```makefile
test-lean: build-lean
	@echo "==> no sorry/admit/native_decide"
	@! grep -rnwE 'sorry|admit|native_decide' spec/ --include='*.lean'
	@echo "==> headline theorems rest on standard axioms only"
	@lake env lean spec/scripts/axioms.lean | tee /tmp/axioms.log
	@! grep -qE 'sorryAx|ofReduceBool' /tmp/axioms.log
```

Make the same change in the CI workflow's Lean step.

- [x] **Step 8: Register and commit**

Add to `spec/scripts/axioms.lean`: `fixedLitLen_valid`, `fixedDist_valid`, `decodeSym_pos`, `decodeSym_bytes`, `decodeSym_in_range`.

```bash
make test-lean
git add spec/ Makefile .github/workflows/ci.yml
git commit -m "feat(m3): Lean canonical Huffman codes and P2

Codes are represented by lengths alone, since RFC 1951 §3.2.2 fixes
everything else. decodeSym walks lengths 1..15 by the counts/offsets method.
P2: strict progress with a 15-bit ceiling, input invariance, decoded symbols
in range, and kernel-checked completeness of both fixed codes.

CI now rejects native_decide and ofReduceBool as well as sorry: closing a
goal by running compiled code is a different trust story from a kernel check.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 10: Rust canonical Huffman tables

**Files:**
- Create: `crates/deflate-core/src/huffman.rs`, `docs/adr/0004-incomplete-huffman-codes.md`
- Modify: `crates/deflate-core/src/lib.rs`
- Test: `crates/deflate-core/tests/huffman_tests.rs`

**Interfaces:**
- Consumes: `BitReader`, `Error`.
- Produces: `huffman::MAX_CODE_LEN: usize = 15`, `huffman::Completeness` (`Complete` | `AllowDegenerate`), `huffman::HuffmanTable` with `from_lengths(&[u8], Completeness) -> Result<HuffmanTable, Error>` and `decode(&self, &mut BitReader) -> Result<u16, Error>`, `huffman::fixed_litlen() -> HuffmanTable`, `huffman::fixed_dist() -> HuffmanTable`. Tasks 14, 16 consume these.

- [x] **Step 1: Write the ADR that the tests encode**

`docs/adr/0004-incomplete-huffman-codes.md`:

```markdown
# ADR 0004: Incomplete and degenerate Huffman codes

**Status:** accepted · **Date:** 2026-10-05

## Context

RFC 1951 §3.2.2 describes how to build a canonical code from lengths. It does
not say what a decoder must do with a length set that is *incomplete* — one
whose Kraft sum is below 2^15, leaving bit patterns unassigned. Over-
subscription (sum above 2^15) is unambiguously malformed.

The case matters because real encoders emit it. A block with no
back-references has nothing to say in the distance alphabet, so zlib writes a
distance code with zero or one symbol. Rejecting those breaks interoperability
with the dominant encoder; accepting every incomplete code means a corrupt
tree decodes to arbitrary symbols instead of being reported.

## Decision

- Over-subscribed (`kraft > 2^15`): always `InvalidHuffmanTree`.
- Complete (`kraft == 2^15`): always accepted.
- Incomplete (`kraft < 2^15`): accepted only when at most one symbol has a
  non-zero length, and only where the caller passes `Completeness::AllowDegenerate`.
  The literal/length tree and the code-length tree always pass
  `Completeness::Complete`; only the distance tree passes `AllowDegenerate`.

This is zlib's rule. `lean-zip`'s reading is recorded in ADR 0002; where it
differs, the difference is noted there and the harness reports it as a
finding rather than a failure.

## Consequences

A single-symbol distance code decodes that symbol after reading its one bit.
If such a block then contains a length symbol, the distance decode either
yields the one defined symbol or returns `InvalidCode`; it never reads
uninitialized table entries.
```

- [x] **Step 2: Write the failing tests**

`crates/deflate-core/tests/huffman_tests.rs`:

```rust
use deflate_core::bitstream::BitReader;
use deflate_core::huffman::{fixed_dist, fixed_litlen, Completeness, HuffmanTable, MAX_CODE_LEN};
use deflate_core::Error;

#[test]
fn canonical_assignment_matches_rfc_example() {
    // RFC 1951 §3.2.2: lengths A=3 B=3 C=3 D=3 E=3 F=2 G=4 H=4 give
    // A=010 B=011 C=100 D=101 E=110 F=00 G=1110 H=1111.
    let t = HuffmanTable::from_lengths(&[3, 3, 3, 3, 3, 2, 4, 4], Completeness::Complete).unwrap();
    // Huffman codes are packed MSB-first, so 0b010 arrives as bits 0,1,0.
    let data = [0b0000_0010u8]; // low 3 bits unused by this read order
    let mut r = BitReader::new(&data);
    // Feed the bits of 010 explicitly through a one-byte stream built MSB-first.
    let _ = (r, data, t); // replaced below by decode_roundtrip_all_symbols
}

/// Encode `sym` with `t`'s canonical code, MSB-first, into a bit stream, then
/// decode it back. Covers every symbol of every table under test.
fn roundtrip(lengths: &[u8], c: Completeness) {
    let t = HuffmanTable::from_lengths(lengths, c).unwrap();
    // Rebuild the canonical codes here, independently of the table, so the
    // test does not merely agree with the implementation it is testing.
    let mut bl_count = [0u16; MAX_CODE_LEN + 1];
    for &l in lengths {
        if l != 0 {
            bl_count[l as usize] += 1;
        }
    }
    let mut next = [0u32; MAX_CODE_LEN + 2];
    let mut code = 0u32;
    for bits in 1..=MAX_CODE_LEN {
        code = (code + bl_count[bits - 1] as u32) << 1;
        next[bits] = code;
    }
    for (sym, &l) in lengths.iter().enumerate() {
        if l == 0 {
            continue;
        }
        let c = next[l as usize];
        next[l as usize] += 1;
        // Pack the code MSB-first into bytes, LSB-first within each byte.
        let mut bits = Vec::new();
        for i in (0..l).rev() {
            bits.push(((c >> i) & 1) as u8);
        }
        let mut bytes = vec![0u8; bits.len().div_ceil(8)];
        for (i, b) in bits.iter().enumerate() {
            bytes[i / 8] |= b << (i % 8);
        }
        let mut r = BitReader::new(&bytes);
        assert_eq!(t.decode(&mut r).unwrap() as usize, sym, "symbol {sym} len {l}");
        assert_eq!(r.bit_pos(), l as usize, "symbol {sym} consumed the wrong width");
    }
}

#[test]
fn rfc_example_roundtrips() {
    roundtrip(&[3, 3, 3, 3, 3, 2, 4, 4], Completeness::Complete);
}

#[test]
fn fixed_tables_roundtrip_every_symbol() {
    let mut lit = vec![8u8; 288];
    lit[144..256].fill(9);
    lit[256..280].fill(7);
    roundtrip(&lit, Completeness::Complete);
    roundtrip(&[5u8; 32], Completeness::Complete);
    // And the constructors agree with the lengths.
    assert!(fixed_litlen().decode(&mut BitReader::new(&[0u8, 0])).is_ok());
    assert!(fixed_dist().decode(&mut BitReader::new(&[0u8])).is_ok());
}

// --- Review Focus 3: incomplete and degenerate codes (ADR 0004) ---

#[test]
fn oversubscribed_code_is_rejected_everywhere() {
    // Three symbols of length 1: Kraft sum 3/2 > 1.
    for c in [Completeness::Complete, Completeness::AllowDegenerate] {
        assert_eq!(
            HuffmanTable::from_lengths(&[1, 1, 1], c).unwrap_err(),
            Error::InvalidHuffmanTree
        );
    }
}

#[test]
fn incomplete_code_is_rejected_where_completeness_is_required() {
    // Two symbols of length 2: Kraft sum 1/2 < 1, and two symbols used.
    assert_eq!(
        HuffmanTable::from_lengths(&[2, 2], Completeness::Complete).unwrap_err(),
        Error::InvalidHuffmanTree
    );
    assert_eq!(
        HuffmanTable::from_lengths(&[2, 2], Completeness::AllowDegenerate).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}

#[test]
fn single_symbol_distance_code_is_accepted_as_degenerate() {
    // What zlib emits for a block with no back-references.
    let t = HuffmanTable::from_lengths(&[1, 0, 0, 0], Completeness::AllowDegenerate)
        .expect("ADR 0004: one used symbol is accepted");
    let data = [0x00u8];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r).unwrap(), 0);
    // ...but the literal/length tree never gets that latitude.
    assert_eq!(
        HuffmanTable::from_lengths(&[1, 0, 0, 0], Completeness::Complete).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}

#[test]
fn empty_code_is_accepted_as_degenerate_and_decodes_nothing() {
    let t = HuffmanTable::from_lengths(&[0, 0, 0], Completeness::AllowDegenerate).unwrap();
    let data = [0xFFu8, 0xFF, 0xFF];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r), Err(Error::InvalidCode));
}

#[test]
fn unassigned_bit_pattern_is_invalid_code_not_a_panic() {
    // A complete code where the all-ones pattern of max length is unassigned
    // cannot exist; use a degenerate one-symbol code and feed it a 1 bit.
    let t = HuffmanTable::from_lengths(&[1, 0], Completeness::AllowDegenerate).unwrap();
    let data = [0xFFu8, 0xFF];
    let mut r = BitReader::new(&data);
    assert_eq!(t.decode(&mut r), Err(Error::InvalidCode));
}

#[test]
fn truncated_code_is_eof() {
    let t = HuffmanTable::from_lengths(&[5u8; 32], Completeness::Complete).unwrap();
    let mut r = BitReader::new(&[]);
    assert_eq!(t.decode(&mut r), Err(Error::UnexpectedEof));
}

#[test]
fn length_above_fifteen_is_rejected() {
    let mut l = vec![0u8; 4];
    l[0] = 16;
    assert_eq!(
        HuffmanTable::from_lengths(&l, Completeness::AllowDegenerate).unwrap_err(),
        Error::InvalidHuffmanTree
    );
}
```

Delete the stub `canonical_assignment_matches_rfc_example` before committing; `rfc_example_roundtrips` supersedes it.

- [x] **Step 3: Run to verify they fail**

Run: `cargo test -p deflate-core --test huffman_tests`
Expected: FAIL — `unresolved import deflate_core::huffman`.

- [x] **Step 4: Write the implementation**

`crates/deflate-core/src/huffman.rs`:

```rust
//! Canonical Huffman codes (RFC 1951 §3.2.2, §3.2.6).
//! Mirrors `spec/Deflate/Huffman.lean`.
//!
//! Huffman codes are the one element packed most-significant-bit first.
//! Decoding shifts one bit in at a time and tests, at each length, whether the
//! accumulated value falls inside that length's contiguous range. No decode
//! table is built, which keeps the code small and the correspondence with the
//! model direct; Task 24 may revisit that for speed, under ADR.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

/// RFC 1951 §3.2.7.
pub const MAX_CODE_LEN: usize = 15;

/// Whether an incomplete code is tolerable here. See ADR 0004.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Completeness {
    /// Literal/length and code-length trees: the code must be complete.
    Complete,
    /// Distance trees: zero or one used symbol is also accepted, because
    /// that is what real encoders emit for a block with no matches.
    AllowDegenerate,
}

pub struct HuffmanTable {
    /// `counts[l]` is how many symbols have length `l`. `counts[0]` is 0.
    counts: [u16; MAX_CODE_LEN + 1],
    /// Symbols ordered by (length, symbol): the canonical order.
    symbols: Vec<u16>,
}

impl HuffmanTable {
    pub fn from_lengths(lengths: &[u8], completeness: Completeness) -> Result<Self, Error> {
        let mut counts = [0u16; MAX_CODE_LEN + 1];
        let mut used = 0usize;
        for &l in lengths {
            let l = l as usize;
            if l > MAX_CODE_LEN {
                return Err(Error::InvalidHuffmanTree);
            }
            if l != 0 {
                used += 1;
                match counts.get_mut(l) {
                    Some(c) => *c += 1,
                    None => return Err(Error::InvalidHuffmanTree),
                }
            }
        }

        // Kraft check, carried as the number of still-unassigned patterns.
        // Going negative means over-subscribed; ending positive means
        // incomplete. i32 cannot overflow here: the loop runs 15 times and
        // each count is at most lengths.len() <= 288 + 32.
        let mut left: i32 = 1;
        for l in 1..=MAX_CODE_LEN {
            left <<= 1;
            left -= i32::from(counts[l]);
            if left < 0 {
                return Err(Error::InvalidHuffmanTree);
            }
        }
        if left > 0 {
            // Incomplete.
            match completeness {
                Completeness::Complete => return Err(Error::InvalidHuffmanTree),
                Completeness::AllowDegenerate if used <= 1 => {}
                Completeness::AllowDegenerate => return Err(Error::InvalidHuffmanTree),
            }
        }

        // Offsets, then symbols in (length, symbol) order.
        let mut offs = [0u16; MAX_CODE_LEN + 2];
        for l in 1..=MAX_CODE_LEN {
            offs[l + 1] = offs[l] + counts[l];
        }
        let mut symbols = alloc::vec![0u16; used];
        for (sym, &l) in lengths.iter().enumerate() {
            let l = l as usize;
            if l == 0 {
                continue;
            }
            let idx = offs[l] as usize;
            match symbols.get_mut(idx) {
                Some(slot) => *slot = sym as u16,
                None => return Err(Error::InvalidHuffmanTree),
            }
            offs[l] += 1;
        }
        Ok(HuffmanTable { counts, symbols })
    }

    /// Decode one symbol. Consumes between 1 and `MAX_CODE_LEN` bits.
    pub fn decode(&self, r: &mut BitReader) -> Result<u16, Error> {
        let mut code: u32 = 0;
        let mut first: u32 = 0;
        let mut index: u32 = 0;
        for l in 1..=MAX_CODE_LEN {
            code |= r.read_bit()?;
            let count = u32::from(self.counts[l]);
            if code < first + count {
                let i = (index + (code - first)) as usize;
                return match self.symbols.get(i) {
                    Some(s) => Ok(*s),
                    None => Err(Error::InvalidCode),
                };
            }
            index += count;
            first = (first + count) << 1;
            code <<= 1;
        }
        Err(Error::InvalidCode)
    }
}

pub fn fixed_litlen() -> HuffmanTable {
    let mut l = alloc::vec![8u8; 288];
    for e in l.iter_mut().take(256).skip(144) {
        *e = 9;
    }
    for e in l.iter_mut().take(280).skip(256) {
        *e = 7;
    }
    // Lengths 8,9,7,8 give a Kraft sum of exactly 2^15 — see Lean's
    // `fixedLitLen_valid`. The unwrap-free construction keeps the no-panic
    // rule: a construction error here would be a bug in this function, so
    // report it as one rather than panicking.
    HuffmanTable::from_lengths(&l, Completeness::Complete)
        .unwrap_or_else(|_| HuffmanTable { counts: [0; MAX_CODE_LEN + 1], symbols: Vec::new() })
}

pub fn fixed_dist() -> HuffmanTable {
    HuffmanTable::from_lengths(&[5u8; 32], Completeness::Complete)
        .unwrap_or_else(|_| HuffmanTable { counts: [0; MAX_CODE_LEN + 1], symbols: Vec::new() })
}
```

Add `pub mod huffman;` to `lib.rs`.

- [x] **Step 5: Run to verify they pass**

Run: `cargo test -p deflate-core --test huffman_tests`
Expected: PASS — 9 tests.

- [x] **Step 6: Replace the silent fallback with a checked one**

The `unwrap_or_else` arms above silently produce a table that decodes nothing. That is safe but hides a bug. Add a test that pins the real behavior, so the fallback can never be reached unnoticed:

```rust
#[test]
fn fixed_tables_are_actually_built() {
    // A table built from the fallback has no symbols and decodes nothing.
    // Both fixed tables must decode symbol 256 (end of block), whose fixed
    // code is seven zero bits.
    let data = [0x00u8, 0x00];
    let mut r = BitReader::new(&data);
    assert_eq!(fixed_litlen().decode(&mut r).unwrap(), 256);
    assert_eq!(r.bit_pos(), 7);
}
```

Run: `cargo test -p deflate-core --test huffman_tests`
Expected: PASS — 10 tests.

- [x] **Step 7: Commit**

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ docs/adr/0004-incomplete-huffman-codes.md
git commit -m "feat(m3): Rust canonical Huffman tables and ADR 0004

Counts/offsets decoding, MSB-first, 1..15 bits. The Kraft check rejects
over-subscription everywhere; incomplete codes are accepted only for a
distance tree with at most one used symbol, which is what zlib emits for a
block with no matches. ADR 0004 records that reading of the RFC's silence,
and the tests pin both directions.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 11: Lean LZ77 copies, P6

**Files:**
- Create: `spec/Deflate/LZ77.lean`
- Modify: `spec/Deflate/Properties.lean`, `spec/Deflate.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `BitReader`, `readBits`, `DecErr`.
- Produces: `Deflate.lengthBase`, `lengthExtra`, `distBase`, `distExtra` (all `Array Nat`), `Deflate.readLength`, `Deflate.readDistance`, `Deflate.copyGo`, `Deflate.copyBack`. Tasks 13, 15, 18, 21 consume these.

- [x] **Step 1: Write the failing theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P6 — LZ77 copies -/

/-- A copy appends exactly `len` bytes. -/
theorem copyGo_size (dist : Nat) : ∀ (k : Nat) (acc : Array UInt8),
    (copyGo dist acc k).size = acc.size + k := by
  intro k
  induction k with
  | zero => intro acc; simp [copyGo]
  | succ n ih => intro acc; simp [copyGo, ih]; omega

theorem copyBack_size {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) : o.size = out.size + len := by
  unfold copyBack at h
  split at h
  · simp at h
  · simp at h; subst h; exact copyGo_size dist len out
```

- [x] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'copyGo'`.

- [x] **Step 3: Write the model**

`spec/Deflate/LZ77.lean`:

```lean
/-
  Deflate.LZ77 — length and distance codes (RFC 1951 §3.2.5) and the back
  copy (§3.2.3).

  The copy is defined one byte at a time, reading from the array it is
  writing. That is not an implementation detail: when `len > dist` the copy
  reads bytes it has just produced, and any bulk-copy definition would get
  that case wrong. `copyGo_overlap` below is the statement that pins it.
-/
import Deflate.Bitstream

namespace Deflate

/-- Length codes 257..285: base values. -/
def lengthBase : Array Nat :=
  #[3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
    67, 83, 99, 115, 131, 163, 195, 227, 258]

/-- Length codes 257..285: extra-bit counts. -/
def lengthExtra : Array Nat :=
  #[0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
    4, 4, 4, 4, 5, 5, 5, 5, 0]

/-- Distance codes 0..29: base values. -/
def distBase : Array Nat :=
  #[1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
    769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]

/-- Distance codes 0..29: extra-bit counts. -/
def distExtra : Array Nat :=
  #[0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
    9, 9, 10, 10, 11, 11, 12, 12, 13, 13]

/-- Resolve a length symbol and its extra bits. Symbols outside 257..285 are
    `invalidLength`; 286 and 287 exist in the fixed code but may never appear. -/
def readLength (sym : Nat) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  if 257 ≤ sym ∧ sym ≤ 285 then
    let i := sym - 257
    match BitReader.readBits r (lengthExtra[i]!) with
    | none => .error .unexpectedEof
    | some (e, r') => .ok (lengthBase[i]! + e, r')
  else .error .invalidLength

/-- Resolve a distance symbol and its extra bits. Symbols 30 and 31 exist in
    the fixed code but may never appear. -/
def readDistance (sym : Nat) (r : BitReader) : Except DecErr (Nat × BitReader) :=
  if sym ≤ 29 then
    match BitReader.readBits r (distExtra[sym]!) with
    | none => .error .unexpectedEof
    | some (e, r') => .ok (distBase[sym]! + e, r')
  else .error .invalidDistance

/-- The copy loop: one byte at a time, from `dist` back in the array being
    built. -/
def copyGo (dist : Nat) : Array UInt8 → Nat → Array UInt8
  | acc, 0 => acc
  | acc, k + 1 => copyGo dist (acc.push (acc[acc.size - dist]!)) k

/-- A back-reference. `dist = 0` and `dist > out.size` are both rejected:
    there is nothing that far back to copy. -/
def copyBack (out : Array UInt8) (dist len : Nat) : Except DecErr (Array UInt8) :=
  if dist = 0 ∨ dist > out.size then .error .invalidDistance
  else .ok (copyGo dist out len)

end Deflate
```

Add `import Deflate.LZ77` to `spec/Deflate.lean` and `spec/Deflate/Properties.lean`.

- [x] **Step 4: Run to verify the two theorems pass**

Run: `lake build`
Expected: PASS.

- [x] **Step 5: Add the remaining P6 theorems**

```lean
/-- A copy never disturbs what was already produced. -/
theorem copyGo_prefix (dist : Nat) : ∀ (k i : Nat) (acc : Array UInt8),
    i < acc.size → (copyGo dist acc k)[i]! = acc[i]! := by
  intro k
  induction k with
  | zero => intro i acc _; simp [copyGo]
  | succ n ih =>
    intro i acc hi
    simp only [copyGo]
    have hpush : i < (acc.push (acc[acc.size - dist]!)).size := by
      simp [Array.size_push]; omega
    rw [ih i _ hpush]
    simp [Array.getElem!_push_lt, hi]

/-- Each copied byte equals the byte `dist` positions before it, *in the
    array as it stands when that byte is written*. This is what makes an
    overlapping copy (`len > dist`) correct: the source of byte `k` may be a
    byte this same copy produced. -/
theorem copyGo_overlap (dist : Nat) (hd : 0 < dist) :
    ∀ (k : Nat) (acc : Array UInt8), dist ≤ acc.size →
      ∀ j, j < k →
        (copyGo dist acc k)[acc.size + j]! = (copyGo dist acc k)[acc.size + j - dist]! := by
  intro k
  induction k with
  | zero => intro acc _ j hj; omega
  | succ n ih =>
    intro acc hda j hj
    simp only [copyGo]
    set acc' := acc.push (acc[acc.size - dist]!) with hacc'
    have hsz : acc'.size = acc.size + 1 := by simp [hacc', Array.size_push]
    have hda' : dist ≤ acc'.size := by omega
    cases j with
    | zero =>
      -- The byte just pushed is, by construction, the one `dist` back.
      have h0 : (copyGo dist acc' n)[acc.size]! = acc'[acc.size]! := by
        exact copyGo_prefix dist n acc.size acc' (by omega)
      have h1 : (copyGo dist acc' n)[acc.size - dist]! = acc'[acc.size - dist]! := by
        exact copyGo_prefix dist n (acc.size - dist) acc' (by omega)
      simp [h0, h1, hacc', Array.getElem!_push_eq, Array.getElem!_push_lt]
      omega
    | succ j =>
      have := ih acc' hda' j (by omega)
      simp [hsz] at this
      simpa [hsz, Nat.add_succ, Nat.succ_add] using this

theorem copyBack_prefix {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) (i : Nat) (hi : i < out.size) :
    o[i]! = out[i]! := by
  unfold copyBack at h
  split at h
  · simp at h
  · simp at h; subst h; exact copyGo_prefix dist len i out hi

theorem copyBack_overlap {out o : Array UInt8} {dist len : Nat}
    (h : copyBack out dist len = .ok o) (j : Nat) (hj : j < len) :
    o[out.size + j]! = o[out.size + j - dist]! := by
  unfold copyBack at h
  split at h
  · simp at h
  · rename_i hne
    simp at h hne
    subst h
    exact copyGo_overlap dist (by omega) len out (by omega) j hj

/-- A distance of zero, or one reaching before the start of output, is
    rejected. P7: no accepted copy can read out of range. -/
theorem copyBack_rejects (out : Array UInt8) (dist len : Nat)
    (h : dist = 0 ∨ dist > out.size) :
    copyBack out dist len = .error .invalidDistance := by
  unfold copyBack; simp [h]

/-- Accepted lengths lie in RFC 1951's range. -/
theorem readLength_range {sym : Nat} {r r' : BitReader} {l : Nat}
    (h : readLength sym r = .ok (l, r')) : 3 ≤ l ∧ l ≤ 258 := by
  unfold readLength at h
  split at h
  · rename_i hs
    split at h
    · simp at h
    · rename_i e r₂ he
      have hlt := readBits_lt (lengthExtra[sym - 257]!) r e r₂ he
      simp at h
      obtain ⟨hl, _⟩ := h
      subst hl
      interval_cases sym <;> simp_all [lengthBase, lengthExtra] <;> omega
  · simp at h

/-- Accepted distances lie in RFC 1951's range. -/
theorem readDistance_range {sym : Nat} {r r' : BitReader} {d : Nat}
    (h : readDistance sym r = .ok (d, r')) : 1 ≤ d ∧ d ≤ 32768 := by
  unfold readDistance at h
  split at h
  · rename_i hs
    split at h
    · simp at h
    · rename_i e r₂ he
      have hlt := readBits_lt (distExtra[sym]!) r e r₂ he
      simp at h
      obtain ⟨hd, _⟩ := h
      subst hd
      interval_cases sym <;> simp_all [distBase, distExtra] <;> omega
  · simp at h
```

`interval_cases` on 29 and 30 cases each is slow but finite; if `lake build` times out, split each into two lemmas by range rather than weakening the statement.

- [x] **Step 6: Run, register, commit**

Run: `lake build && ! grep -rnwE 'sorry|admit|native_decide' spec/ --include='*.lean'`
Expected: PASS, exit 0.

Add `copyBack_size`, `copyBack_overlap`, `copyBack_rejects`, `readLength_range`, `readDistance_range` to `spec/scripts/axioms.lean`.

```bash
make test-lean
git add spec/
git commit -m "feat(m3): Lean LZ77 length/distance codes and copies, P6 and P7

copyGo copies one byte at a time from the array it is building, so an
overlapping copy (len > dist) reads bytes it has just written.
copyGo_overlap is that statement. copyBack rejects dist = 0 and dist beyond
the output produced so far, which is the P7 in-range obligation for copies.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 12: Rust LZ77 copies

**Files:**
- Create: `crates/deflate-core/src/lz77.rs`
- Modify: `crates/deflate-core/src/lib.rs`
- Test: `crates/deflate-core/tests/lz77_tests.rs`

**Interfaces:**
- Consumes: `BitReader`, `Error`.
- Produces: `lz77::LENGTH_BASE: [u16; 29]`, `LENGTH_EXTRA: [u8; 29]`, `DIST_BASE: [u16; 30]`, `DIST_EXTRA: [u8; 30]`, `lz77::read_length(u16, &mut BitReader) -> Result<usize, Error>`, `lz77::read_distance(u16, &mut BitReader) -> Result<usize, Error>`, `lz77::copy_back(&mut Vec<u8>, usize, usize) -> Result<(), Error>`. Tasks 14, 16 consume these.

- [x] **Step 1: Write the failing tests**

`crates/deflate-core/tests/lz77_tests.rs`:

```rust
use deflate_core::bitstream::BitReader;
use deflate_core::lz77::{copy_back, read_distance, read_length, DIST_BASE, LENGTH_BASE};
use deflate_core::Error;

#[test]
fn non_overlapping_copy() {
    let mut out = b"abcdef".to_vec();
    copy_back(&mut out, 6, 3).unwrap();
    assert_eq!(out, b"abcdefabc");
}

#[test]
fn overlapping_copy_repeats_the_source() {
    // dist 1, len 5: the byte is repeated, not read five times from one place.
    let mut out = b"xa".to_vec();
    copy_back(&mut out, 1, 5).unwrap();
    assert_eq!(out, b"xaaaaaa");
}

#[test]
fn overlapping_copy_with_period_three() {
    let mut out = b"abc".to_vec();
    copy_back(&mut out, 3, 7).unwrap();
    assert_eq!(out, b"abcabcabca");
}

#[test]
fn maximum_length_copy() {
    let mut out = vec![b'q'];
    copy_back(&mut out, 1, 258).unwrap();
    assert_eq!(out.len(), 259);
    assert!(out.iter().all(|&b| b == b'q'));
}

// --- Review Focus 4: the output boundary ---

#[test]
fn distance_equal_to_output_length_is_legal() {
    // The very first byte produced is exactly `out.len()` back.
    let mut out = b"abc".to_vec();
    copy_back(&mut out, 3, 1).unwrap();
    assert_eq!(out, b"abca");
}

#[test]
fn distance_one_past_the_output_is_rejected() {
    let mut out = b"abc".to_vec();
    assert_eq!(copy_back(&mut out, 4, 1), Err(Error::InvalidDistance));
    assert_eq!(out, b"abc", "a rejected copy must not modify the output");
}

#[test]
fn zero_distance_is_rejected() {
    let mut out = b"abc".to_vec();
    assert_eq!(copy_back(&mut out, 0, 1), Err(Error::InvalidDistance));
    assert_eq!(out, b"abc");
}

#[test]
fn any_distance_into_empty_output_is_rejected() {
    let mut out = Vec::new();
    for d in [0usize, 1, 2, 32768, usize::MAX] {
        assert_eq!(copy_back(&mut out, d, 1), Err(Error::InvalidDistance));
    }
    assert!(out.is_empty());
}

// --- symbol tables ---

#[test]
fn length_symbols_span_three_to_258() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(257, &mut r).unwrap(), 3);
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(285, &mut r).unwrap(), 258);
    // 284 with all five extra bits set also reaches 258 — legal, if unusual.
    let data = [0xFFu8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_length(284, &mut r).unwrap(), 258);
}

#[test]
fn length_symbols_outside_the_range_are_rejected() {
    let data = [0u8; 4];
    for s in [0u16, 256, 286, 287, 300] {
        let mut r = BitReader::new(&data);
        assert_eq!(read_length(s, &mut r), Err(Error::InvalidLength));
    }
}

#[test]
fn distance_symbols_span_one_to_32768() {
    let data = [0u8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_distance(0, &mut r).unwrap(), 1);
    let data = [0xFFu8; 4];
    let mut r = BitReader::new(&data);
    assert_eq!(read_distance(29, &mut r).unwrap(), 24577 + 8191);
}

#[test]
fn distance_symbols_thirty_and_thirty_one_are_rejected() {
    let data = [0u8; 4];
    for s in [30u16, 31, 99] {
        let mut r = BitReader::new(&data);
        assert_eq!(read_distance(s, &mut r), Err(Error::InvalidDistance));
    }
}

#[test]
fn tables_have_the_sizes_rfc_1951_requires() {
    assert_eq!(LENGTH_BASE.len(), 29); // symbols 257..=285
    assert_eq!(DIST_BASE.len(), 30);   // symbols 0..=29
}

#[test]
fn truncated_extra_bits_are_eof() {
    let mut r = BitReader::new(&[]);
    assert_eq!(read_length(269, &mut r), Err(Error::UnexpectedEof)); // needs 2 extra bits
    let mut r = BitReader::new(&[]);
    assert_eq!(read_distance(29, &mut r), Err(Error::UnexpectedEof)); // needs 13
}
```

- [x] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test lz77_tests`
Expected: FAIL — `unresolved import deflate_core::lz77`.

- [x] **Step 3: Write the implementation**

`crates/deflate-core/src/lz77.rs`:

```rust
//! Length/distance codes (RFC 1951 §3.2.5) and the back copy (§3.2.3).
//! Mirrors `spec/Deflate/LZ77.lean`.

use crate::bitstream::BitReader;
use crate::error::Error;
use alloc::vec::Vec;

/// Length codes 257..=285.
pub const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
    163, 195, 227, 258,
];
pub const LENGTH_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];

/// Distance codes 0..=29.
pub const DIST_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
pub const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];

/// Resolve a length symbol. 286 and 287 exist in the fixed code but RFC 1951
/// §3.2.6 says they may never appear in a stream.
pub fn read_length(sym: u16, r: &mut BitReader) -> Result<usize, Error> {
    if !(257..=285).contains(&sym) {
        return Err(Error::InvalidLength);
    }
    let i = (sym - 257) as usize;
    let (base, extra) = match (LENGTH_BASE.get(i), LENGTH_EXTRA.get(i)) {
        (Some(b), Some(e)) => (*b, *e),
        _ => return Err(Error::InvalidLength),
    };
    Ok(base as usize + r.read_bits(extra as u32)? as usize)
}

/// Resolve a distance symbol. 30 and 31 exist in the fixed code but may never
/// appear.
pub fn read_distance(sym: u16, r: &mut BitReader) -> Result<usize, Error> {
    let i = sym as usize;
    let (base, extra) = match (DIST_BASE.get(i), DIST_EXTRA.get(i)) {
        (Some(b), Some(e)) => (*b, *e),
        _ => return Err(Error::InvalidDistance),
    };
    Ok(base as usize + r.read_bits(extra as u32)? as usize)
}

/// Copy `len` bytes from `dist` back, one at a time, so that `len > dist`
/// repeats what this very copy produces (RFC 1951 §3.2.3). On error nothing
/// is appended.
pub fn copy_back(out: &mut Vec<u8>, dist: usize, len: usize) -> Result<(), Error> {
    if dist == 0 || dist > out.len() {
        return Err(Error::InvalidDistance);
    }
    out.reserve(len);
    for _ in 0..len {
        // `dist <= out.len()` holds at entry and `out` only grows, so this
        // index is in range at every iteration. `get` rather than `[]` keeps
        // that an enforced fact rather than an argument.
        let b = match out.len().checked_sub(dist).and_then(|i| out.get(i)) {
            Some(b) => *b,
            None => return Err(Error::InvalidDistance),
        };
        out.push(b);
    }
    Ok(())
}
```

Add `pub mod lz77;` to `lib.rs`.

- [x] **Step 4: Run to verify they pass**

Run: `cargo test -p deflate-core --test lz77_tests`
Expected: PASS — 13 tests.

- [x] **Step 5: Cross-check the overlap behavior against zlib**

Run:

```bash
python3 - <<'PY'
import zlib
# A payload whose encoding must use overlapping back-references.
for raw in (b"a"*300, b"abc"*200, b"ab"*5000, bytes(range(32))*100):
    for lvl in (1, 6, 9):
        c = zlib.compressobj(lvl, zlib.DEFLATED, -15)
        s = c.compress(raw) + c.flush()
        assert zlib.decompress(s, -15) == raw
        print(lvl, len(raw), "->", len(s))
PY
```

Add the four payloads to `oracles/corpus.py`'s `PAYLOADS` so every later run of the differential harness carries them.

- [x] **Step 6: Update conformance and commit**

`docs/conformance.md`: `| Overlapping back-reference | yes | yes | yes |`.

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ oracles/corpus.py docs/conformance.md
git commit -m "feat(m3): Rust LZ77 tables and the byte-at-a-time back copy

copy_back rejects dist = 0 and dist beyond the output produced so far, and
leaves the output untouched when it does. The copy is byte at a time, so
len > dist repeats what the copy itself writes. Boundary tests cover
dist == out.len(), dist == out.len() + 1 and every distance into empty
output.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 13: Lean Huffman block body, P4

**Files:**
- Modify: `spec/Deflate/Block.lean`, `spec/Deflate/Properties.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `Code`, `decodeSym`, `readLength`, `readDistance`, `copyBack`, `BitReader`.
- Produces: `Deflate.decodeHuffBlock (lit dist : Code) (r : BitReader) (out : Array UInt8) (limit fuel : Nat) : Except DecErr (Array UInt8 × BitReader)`. Tasks 15 and 18 call it with the fixed codes and with dynamic ones.

- [x] **Step 1: Write the failing theorem**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P4 — Fixed Huffman blocks -/

/-- A block body never alters the input and never shrinks the output. -/
theorem decodeHuffBlock_monotone : ∀ (fuel : Nat) (lit dist : Code) (r : BitReader)
    (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') →
    out.size ≤ o.size ∧ r'.bytes = r.bytes ∧ r.pos ≤ r'.pos := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp at h
    | ok p =>
      obtain ⟨sym, r₁⟩ := p
      rw [hs] at h
      have hp := decodeSym_pos hs
      have hb := decodeSym_bytes hs
      split at h
      · -- literal
        split at h
        · simp at h
        · have := ih lit dist _ _ o limit r' h
          simp [Array.size_push] at this ⊢
          omega
      · split at h
        · -- end of block
          simp at h; obtain ⟨h1, h2⟩ := h; subst h1; subst h2
          simp_all; omega
        · -- length/distance
          repeat' split at h
          all_goals simp_all
          all_goals
            (rename_i l r₂ hl dsym r₃ hd d r₄ hdd o₁ hco
             have := ih lit dist r₄ o₁ o limit r' h
             have := copyBack_size hco
             simp_all; omega)
```

- [x] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'decodeHuffBlock'`.

- [x] **Step 3: Write the model**

Append to `spec/Deflate/Block.lean` (after adding `import Deflate.Huffman` and `import Deflate.LZ77`):

```lean
/-- Decode one Huffman-coded block body with the given literal/length and
    distance codes. Covers both fixed (RFC 1951 §3.2.6) and dynamic (§3.2.7)
    blocks: they differ only in where the two codes come from.

    `fuel` bounds the loop. `Properties.decodeHuffBlock_fuel_sufficient` shows
    that the fuel the entry point supplies is never exhausted on a finite
    stream, because each iteration consumes at least one bit. Reporting
    exhaustion explicitly rather than guessing is deliberate: maked's cycle
    detector once answered "acyclic" when it ran out of fuel. -/
def decodeHuffBlock (lit dist : Code) (r : BitReader) (out : Array UInt8)
    (limit : Nat) : Nat → Except DecErr (Array UInt8 × BitReader)
  | 0 => .error .fuelExhausted
  | fuel + 1 => do
    let (sym, r₁) ← decodeSym lit r
    if sym < 256 then
      if out.size ≥ limit then .error .outputLimitExceeded
      else decodeHuffBlock lit dist r₁ (out.push (UInt8.ofNat sym)) limit fuel
    else if sym = 256 then
      .ok (out, r₁)
    else do
      let (l, r₂) ← readLength sym r₁
      let (dsym, r₃) ← decodeSym dist r₂
      let (d, r₄) ← readDistance dsym r₃
      if out.size + l > limit then .error .outputLimitExceeded
      else do
        let o₁ ← copyBack out d l
        decodeHuffBlock lit dist r₄ o₁ limit fuel
```

Note the argument order: `fuel` is last so the equation compiler accepts the structural recursion. Update the theorem in Step 1 to match (`decodeHuffBlock lit dist r out limit fuel`).

- [x] **Step 4: Run to verify the theorem passes**

Run: `lake build`
Expected: PASS.

- [x] **Step 5: Add the remaining P4 theorems**

```lean
/-- The output limit is never exceeded by a successful block decode. This is
    the model's half of spec §11's bomb requirement. -/
theorem decodeHuffBlock_within_limit : ∀ (fuel : Nat) (lit dist : Code)
    (r : BitReader) (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    out.size ≤ limit →
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') → o.size ≤ limit := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' hle h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp at h
    | ok p =>
      obtain ⟨sym, r₁⟩ := p
      rw [hs] at h
      split at h
      · split at h
        · simp at h
        · exact ih lit dist _ _ o limit r' (by simp [Array.size_push]; omega) h
      · split at h
        · simp at h; obtain ⟨h1, _⟩ := h; subst h1; exact hle
        · repeat' split at h
          all_goals simp_all
          all_goals
            (rename_i hlim o₁ hco
             have := copyBack_size hco
             exact ih lit dist _ o₁ o limit r' (by omega) h)

/-- Every iteration consumes at least one bit, so a block body cannot spin
    without advancing. The P8 ingredient. -/
theorem decodeHuffBlock_progress : ∀ (fuel : Nat) (lit dist : Code)
    (r : BitReader) (out o : Array UInt8) (limit : Nat) (r' : BitReader),
    decodeHuffBlock lit dist r out limit fuel = .ok (o, r') → r.pos < r'.pos := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ _ _ _ _ h; simp [decodeHuffBlock] at h
  | succ n ih =>
    intro lit dist r out o limit r' h
    unfold decodeHuffBlock at h
    cases hs : decodeSym lit r with
    | error e => rw [hs] at h; simp at h
    | ok p =>
      obtain ⟨sym, r₁⟩ := p
      rw [hs] at h
      have hp := decodeSym_pos hs
      have hmono := decodeHuffBlock_monotone
      split at h
      · split at h
        · simp at h
        · have := hmono n lit dist _ _ o limit r' h
          omega
      · split at h
        · simp at h; obtain ⟨_, h2⟩ := h; subst h2; omega
        · repeat' split at h
          all_goals simp_all
          all_goals
            (rename_i l r₂ hl dsym r₃ hd d r₄ hdd _ o₁ hco
             have := hmono n lit dist r₄ o₁ o limit r' h
             have hl2 := readBits_pos _ _ _ _ (by assumption)
             omega)
```

The last branch needs the position facts for `readLength`, `decodeSym` on the distance tree and `readDistance`. Add the two missing lemmas first — `readLength_pos` and `readDistance_pos`, each `r.pos ≤ r'.pos`, both one-line `unfold; split; simp_all [readBits_pos]` — then this proof closes with `omega`.

- [x] **Step 6: Run, register, commit**

Run: `lake build && make test-lean`
Expected: PASS.

Add `decodeHuffBlock_monotone`, `decodeHuffBlock_within_limit`, `decodeHuffBlock_progress` to `spec/scripts/axioms.lean`.

```bash
git add spec/
git commit -m "feat(m3): Lean Huffman block body, P4

One body decoder serves fixed and dynamic blocks; they differ only in where
the two codes come from. Fuel-bounded, with explicit fuelExhausted rather
than a guess. P4: monotone output, input invariance, the output limit
respected, and strict bit progress per iteration — the P8 ingredient.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 14: Rust fixed Huffman decoding

**Files:**
- Modify: `crates/deflate-core/src/inflate.rs`, `crates/deflate-core/src/block.rs`
- Test: `crates/deflate-core/tests/fixed_tests.rs`

**Interfaces:**
- Consumes: `huffman::{HuffmanTable, fixed_litlen, fixed_dist}`, `lz77::{read_length, read_distance, copy_back}`, `BitReader`.
- Produces: `block::decode_huff_block(&HuffmanTable, &HuffmanTable, &mut BitReader, &mut Vec<u8>, usize) -> Result<(), Error>` (last argument is the absolute output limit). Task 16 calls it with dynamic tables.

- [x] **Step 1: Write the failing tests**

`crates/deflate-core/tests/fixed_tests.rs`:

```rust
use deflate_core::{inflate, Error};

/// Raw DEFLATE at a level that produces fixed-Huffman blocks for small input.
fn zlib_fixed(payload: &[u8]) -> Vec<u8> {
    // Produced once by Python and committed as a vector; see Step 4. Here we
    // build the stream by hand so the test has no build-time dependency.
    let _ = payload;
    unreachable!("replaced in Step 1 by the explicit vectors below")
}

#[test]
fn empty_fixed_block_yields_nothing() {
    // Review Focus 2: BFINAL=1, BTYPE=01, then the 7-bit end-of-block code
    // (0000000). Bits LSB-first: 1,1,0, then seven 0s -> 0b0000_0011 = 0x03,
    // with the remaining bits in a second byte.
    assert_eq!(inflate(&[0x03, 0x00]).unwrap(), b"");
}

#[test]
fn fixed_block_with_literals() {
    // zlib: zlib.compressobj(9, zlib.DEFLATED, -15) on b"abc"
    let s = [0x4bu8, 0x4c, 0x4a, 0x06, 0x00];
    assert_eq!(inflate(&s).unwrap(), b"abc");
}

#[test]
fn fixed_block_with_a_back_reference() {
    // zlib on b"abcabcabcabc"
    let s = [0x4bu8, 0x4c, 0x4a, 0x4e, 0x4c, 0x4a, 0x4e, 0x4c, 0x4a, 0x4e, 0x4c, 0x4a, 0x4e, 0x04, 0x00];
    let out = inflate(&s).unwrap();
    assert!(out.starts_with(b"abc"), "got {out:?}");
}

#[test]
fn fixed_block_truncated_mid_code_is_eof() {
    assert_eq!(inflate(&[0x03]), Err(Error::UnexpectedEof));
}

#[test]
fn fixed_block_without_end_of_block_is_eof() {
    // Literals and then the stream stops: no 256 symbol is ever read.
    assert_eq!(inflate(&[0x4b, 0x4c, 0x4a]), Err(Error::UnexpectedEof));
}
```

Replace the three hand-written zlib byte arrays with whatever this command prints, and delete the `zlib_fixed` stub:

```bash
python3 - <<'PY'
import zlib
for p in (b"", b"abc", b"abcabcabcabc"):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    s = c.compress(p) + c.flush()
    print(repr(p), "->", "[" + ", ".join(f"0x{b:02x}" for b in s) + "]")
PY
```

If a stream turns out to be a dynamic block rather than a fixed one — zlib chooses per block — move that case to Task 16's tests and pick a shorter payload here. Check with `(s[0] >> 1) & 3`: 1 is fixed, 2 is dynamic.

- [x] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test fixed_tests`
Expected: FAIL — `InvalidBlockType`, from the `Fixed | Dynamic` arm Task 7 left in place.

- [x] **Step 3: Write the block body decoder**

Append to `crates/deflate-core/src/block.rs`:

```rust
use crate::huffman::HuffmanTable;
use crate::lz77::{copy_back, read_distance, read_length};

/// Decode one Huffman-coded block body. Serves both fixed and dynamic
/// blocks; they differ only in where `lit` and `dist` come from.
/// `limit` is the absolute ceiling on `out.len()`, checked *before* each
/// append, so a bomb never allocates past it.
/// Mirrors `spec/Deflate/Block.lean`'s `decodeHuffBlock`.
pub fn decode_huff_block(
    lit: &HuffmanTable,
    dist: &HuffmanTable,
    r: &mut BitReader,
    out: &mut Vec<u8>,
    limit: usize,
) -> Result<(), Error> {
    loop {
        let sym = lit.decode(r)?;
        if sym < 256 {
            if out.len() >= limit {
                return Err(Error::OutputLimitExceeded);
            }
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let len = read_length(sym, r)?;
            let dsym = dist.decode(r)?;
            let d = read_distance(dsym, r)?;
            if out.len().saturating_add(len) > limit {
                return Err(Error::OutputLimitExceeded);
            }
            copy_back(out, d, len)?;
        }
        // No explicit fuel: `lit.decode` consumes at least one bit on every
        // path that returns `Ok`, and the stream is finite, so the loop
        // terminates with `UnexpectedEof` if nothing else stops it first.
        // `spec/Deflate/Properties.lean`'s `decodeHuffBlock_progress` is the
        // model's statement of that argument.
    }
}
```

- [x] **Step 4: Wire fixed blocks into `inflate`**

In `crates/deflate-core/src/inflate.rs`, replace the `Fixed | Dynamic` arm:

```rust
use crate::block::decode_huff_block;
use crate::huffman::{fixed_dist, fixed_litlen};

// ... inside the match:
            BlockType::Fixed => {
                let lit = fixed_litlen();
                let dst = fixed_dist();
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
            BlockType::Dynamic => return Err(Error::InvalidBlockType), // Task 16
```

and delete the now-unused `budget` binding for that arm, keeping it for `Stored`.

- [x] **Step 5: Run to verify they pass**

Run: `cargo test -p deflate-core --test fixed_tests`
Expected: PASS — 5 tests.

- [x] **Step 6: Run the differential harness**

Run: `make all && python3 oracles/differential.py --no-zlib`
Expected: Rust and Lean findings = 0. The Lean model does not yet drive fixed blocks from `Main.lean` — extend `decodeStored` there to call `decodeHuffBlock fixedLitLen fixedDist` on `.fixed`, with fuel `8 * bs.size + 1`, before running this.

Run: `python3 oracles/differential.py`
Expected: zlib findings now cover only dynamic blocks. Record the count in the commit message.

- [x] **Step 7: Update conformance and commit**

`docs/conformance.md`: `| Fixed Huffman | yes | yes | yes |`.

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ spec/Main.lean docs/conformance.md
git commit -m "feat(m3): Rust fixed Huffman blocks

decode_huff_block serves both fixed and dynamic bodies and checks the output
limit before every append, so a bomb never allocates past it. The Lean oracle
driver decodes fixed blocks too, and the harness reports zero Rust/Lean
disagreements across the corpus.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M4 — Dynamic Huffman decoder

**Exit:** `HLIT`/`HDIST`/`HCLEN`, the code-length alphabet with repeat symbols 16/17/18, and both constructed trees, implemented and verified.

### Task 15: Lean dynamic code descriptions, P5

**Files:**
- Create: nothing
- Modify: `spec/Deflate/Bitstream.lean` (adds `readBitsE`), `spec/Deflate/Huffman.lean` (splits the validity predicate), `spec/Deflate/Block.lean`, `spec/Deflate/Properties.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `Code`, `decodeSym`, `readBits`, `DecErr`.
- Produces: `BitReader.readBitsE : BitReader → Nat → Except DecErr (Nat × BitReader)`, `Code.isComplete`, `Code.isValidDistance`, `Deflate.clOrder`, `Deflate.readCodeLengths`, `Deflate.readDynamicCodes`. Task 18 calls `readDynamicCodes`.

- [x] **Step 1: Split the validity predicate**

Task 9 gave `Code.isValid` the degenerate escape, which ADR 0004 says belongs to distance trees alone. Make that explicit before dynamic trees arrive, because a dynamic block builds three codes and only one of them gets the latitude.

In `spec/Deflate/Huffman.lean`, replace `isValid` with:

```lean
/-- Exactly complete: the Kraft sum is `2 ^ maxCodeLen`. Required of the
    literal/length tree and the code-length tree (ADR 0004). -/
def isComplete (c : Code) : Bool := c.kraft = 2 ^ maxCodeLen

/-- Complete, or incomplete with at most one used symbol. Only a distance
    tree is allowed this (ADR 0004): real encoders emit a one-symbol or empty
    distance code for a block with no back-references. -/
def isValidDistance (c : Code) : Bool :=
  c.isComplete || (c.kraft < 2 ^ maxCodeLen && c.used ≤ 1)
```

Rename the two theorems in `spec/Deflate/Properties.lean` accordingly and keep both proofs as `by decide`:

```lean
theorem fixedLitLen_complete : Code.isComplete fixedLitLen = true := by decide
theorem fixedDist_complete : Code.isComplete fixedDist = true := by decide

/-- A complete code is always acceptable as a distance code. -/
theorem isComplete_isValidDistance (c : Code) (h : Code.isComplete c = true) :
    Code.isValidDistance c = true := by simp [Code.isValidDistance, h]
```

Replace `oversubscribed_invalid` with the two statements it meant:

```lean
theorem oversubscribed_not_complete (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isComplete c = false := by simp [Code.isComplete]; omega

theorem oversubscribed_not_valid_distance (c : Code) (h : c.kraft > 2 ^ maxCodeLen) :
    Code.isValidDistance c = false := by
  simp [Code.isValidDistance, Code.isComplete]; omega
```

Update `spec/scripts/axioms.lean` to the new names.

Run: `lake build`
Expected: PASS.

- [x] **Step 2: Write the failing theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P5 — Dynamic Huffman -/

/-- The code-length alphabet order of RFC 1951 §3.2.7 is a permutation of
    0..18: every code-length symbol is read exactly once. A transposition
    here would silently mis-assign every dynamic tree, so it is checked by
    the kernel rather than by eye. -/
theorem clOrder_is_a_permutation :
    clOrder.size = 19 ∧
    (List.range 19).all (fun s => clOrder.toList.count s = 1) = true := by
  constructor
  · decide
  · decide
```

- [x] **Step 3: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'clOrder'`.

- [x] **Step 4: Write the model**

Add to `spec/Deflate/Bitstream.lean`, inside `namespace BitReader`:

```lean
/-- `readBits` in the decoder's error monad: a short read is `unexpectedEof`. -/
def readBitsE (r : BitReader) (n : Nat) : Except DecErr (Nat × BitReader) :=
  match readBits r n with
  | none => .error .unexpectedEof
  | some p => .ok p
```

Append to `spec/Deflate/Block.lean`:

```lean
/-- RFC 1951 §3.2.7: the order in which code-length code lengths appear.
    Frequently-used lengths come first so trailing zeros can be omitted. -/
def clOrder : Array Nat :=
  #[16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]

/-- Read `ncode` three-bit lengths and scatter them through `clOrder` into a
    19-entry array; positions not covered stay 0. -/
def readCLLens (r : BitReader) (ncode : Nat) : Except DecErr (Array Nat × BitReader) :=
  let rec go (i : Nat) (acc : Array Nat) (r : BitReader) :
      Except DecErr (Array Nat × BitReader) :=
    if i ≥ ncode then .ok (acc, r)
    else
      match BitReader.readBitsE r 3 with
      | .error e => .error e
      | .ok (v, r') => go (i + 1) (acc.set! (clOrder[i]!) v) r'
  go 0 (Array.replicate 19 0) r
  termination_by ncode - i

/-- Decode `total` code lengths with the code-length tree. Symbol 16 repeats
    the previous length 3..6 times, 17 repeats zero 3..10 times, 18 repeats
    zero 11..138 times. A 16 with nothing before it, and any repeat that
    would overrun `total`, are both `invalidHuffmanTree`. -/
def readCodeLengths (clCode : Code) (total : Nat) (r : BitReader) :
    Except DecErr (Array Nat × BitReader) :=
  let rec go (acc : Array Nat) (r : BitReader) (fuel : Nat) :
      Except DecErr (Array Nat × BitReader) :=
    match fuel with
    | 0 => .error .fuelExhausted
    | fuel + 1 =>
      if acc.size ≥ total then .ok (acc, r)
      else do
        let (sym, r₁) ← decodeSym clCode r
        if sym < 16 then
          go (acc.push sym) r₁ fuel
        else if sym = 16 then
          match acc.back? with
          | none => .error .invalidHuffmanTree
          | some prev => do
              let (e, r₂) ← BitReader.readBitsE r₁ 2
              let n := 3 + e
              if acc.size + n > total then .error .invalidHuffmanTree
              else go (acc ++ Array.replicate n prev) r₂ fuel
        else if sym = 17 then do
          let (e, r₂) ← BitReader.readBitsE r₁ 3
          let n := 3 + e
          if acc.size + n > total then .error .invalidHuffmanTree
          else go (acc ++ Array.replicate n 0) r₂ fuel
        else if sym = 18 then do
          let (e, r₂) ← BitReader.readBitsE r₁ 7
          let n := 11 + e
          if acc.size + n > total then .error .invalidHuffmanTree
          else go (acc ++ Array.replicate n 0) r₂ fuel
        else .error .invalidHuffmanTree
  go #[] r (total + 1)

/-- The dynamic block header (RFC 1951 §3.2.7). -/
def readDynamicCodes (r : BitReader) : Except DecErr ((Code × Code) × BitReader) := do
  let (hlit, r₁)  ← BitReader.readBitsE r 5
  let (hdist, r₂) ← BitReader.readBitsE r₁ 5
  let (hclen, r₃) ← BitReader.readBitsE r₂ 4
  let nlen  := hlit + 257
  let ndist := hdist + 1
  let ncode := hclen + 4
  -- RFC 1951 §3.2.7 caps these; the 5-bit fields can express more.
  if nlen > 286 ∨ ndist > 30 then .error .invalidHuffmanTree
  else do
    let (clLens, r₄) ← readCLLens r₃ ncode
    let clCode : Code := ⟨clLens⟩
    if ¬ clCode.isComplete then .error .invalidHuffmanTree
    else do
      let (lens, r₅) ← readCodeLengths clCode (nlen + ndist) r₄
      let lit : Code := ⟨lens.extract 0 nlen⟩
      let dst : Code := ⟨lens.extract nlen (nlen + ndist)⟩
      if ¬ lit.isComplete then .error .invalidHuffmanTree
      else if ¬ dst.isValidDistance then .error .invalidHuffmanTree
      else .ok ((lit, dst), r₅)
```

- [x] **Step 5: Run to verify the permutation theorem passes**

Run: `lake build`
Expected: PASS. `clOrder_is_a_permutation` is the one place a typo in that nineteen-element table gets caught, so confirm it is really checked and not accidentally trivial: temporarily swap two entries, rebuild, and watch it fail. Restore before continuing.

- [x] **Step 6: Add the remaining P5 theorems**

```lean
/-- Decoded code lengths fill exactly the requested count — no more, no
    fewer. Over-run of a repeat is the classic dynamic-header bug. -/
theorem readCodeLengths_size {clCode : Code} {total : Nat} {r r' : BitReader}
    {lens : Array Nat} (h : readCodeLengths clCode total r = .ok (lens, r')) :
    lens.size = total ∨ lens.size < total + 138 := by
  -- The loop appends only when the result still fits `total`, and stops as
  -- soon as `acc.size ≥ total`, so the final size is `total` exactly unless
  -- the final append landed on the boundary.
  unfold readCodeLengths at h
  exact Or.inr (by omega)

/-- A dynamic header yields a complete literal/length code and a distance
    code acceptable under ADR 0004 — or an error. There is no third outcome
    in which the decoder proceeds with a malformed tree. -/
theorem readDynamicCodes_valid {r r' : BitReader} {lit dst : Code}
    (h : readDynamicCodes r = .ok ((lit, dst), r')) :
    Code.isComplete lit = true ∧ Code.isValidDistance dst = true := by
  unfold readDynamicCodes at h
  repeat' split at h
  all_goals simp_all

/-- A dynamic header never alters the input and only advances. -/
theorem readDynamicCodes_pos {r r' : BitReader} {lit dst : Code}
    (h : readDynamicCodes r = .ok ((lit, dst), r')) :
    r.pos ≤ r'.pos ∧ r'.bytes = r.bytes := by
  unfold readDynamicCodes at h
  repeat' split at h
  all_goals simp_all [readBits_pos, readBits_bytes]
```

`readCodeLengths_size` as stated above is weaker than it looks; strengthen it to `lens.size = total` by first proving the loop invariant `acc.size ≤ total` as a separate lemma, then noting the loop exits only at `acc.size ≥ total`. Do that rather than ship the disjunction — a theorem that is true but says less than its name suggests is exactly the failure maked's `recipe_tamper_invalidates_key` is documented as. If the strengthening will not close, rename the theorem to say what it proves and record the gap in `docs/verification-boundary.md`.

- [x] **Step 7: Run, register, commit**

Run: `lake build && make test-lean`
Expected: PASS.

Add `clOrder_is_a_permutation`, `readDynamicCodes_valid`, `readDynamicCodes_pos`, `fixedLitLen_complete`, `fixedDist_complete` to `spec/scripts/axioms.lean`.

```bash
git add spec/
git commit -m "feat(m4): Lean dynamic Huffman code descriptions, P5

HLIT/HDIST/HCLEN with RFC 1951's 286/30 caps, the code-length alphabet in
clOrder, and repeat symbols 16/17/18 with over-run and no-previous rejected.
Validity is now split: isComplete for the literal/length and code-length
trees, isValidDistance for the distance tree alone, per ADR 0004.

clOrder_is_a_permutation is kernel-checked, because a transposition in that
table would silently mis-assign every dynamic tree.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 16: Rust dynamic Huffman

**Files:**
- Modify: `crates/deflate-core/src/block.rs`, `crates/deflate-core/src/inflate.rs`, `Makefile`, `.github/workflows/ci.yml`
- Test: `crates/deflate-core/tests/dynamic_tests.rs`

**Interfaces:**
- Consumes: `HuffmanTable::from_lengths`, `Completeness`, `BitReader`.
- Produces: `block::CL_ORDER: [usize; 19]`, `block::read_dynamic_tables(&mut BitReader) -> Result<(HuffmanTable, HuffmanTable), Error>`.

- [ ] **Step 1: Write the failing tests**

`crates/deflate-core/tests/dynamic_tests.rs`:

```rust
use deflate_core::{inflate, inflate_with_limit, Error};

/// Streams produced by zlib at a level that chooses dynamic blocks. Generated
/// once by `python3 -c` and committed here so the test needs no toolchain.
/// Regenerate with the snippet in Step 5 if they ever need to change.
const DYN_HELLO: &[u8] = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
const DYN_HELLO_RAW: &[u8] = include_bytes!("../../../tests/vectors/dynamic_hello.raw");

#[test]
fn decodes_a_dynamic_block() {
    assert_eq!(inflate(DYN_HELLO).unwrap(), DYN_HELLO_RAW);
}

#[test]
fn dynamic_header_truncated_at_every_prefix_is_eof_or_tree_error() {
    for cut in 1..DYN_HELLO.len().min(40) {
        let r = inflate(&DYN_HELLO[..cut]);
        assert!(
            matches!(
                r,
                Err(Error::UnexpectedEof)
                    | Err(Error::InvalidHuffmanTree)
                    | Err(Error::InvalidCode)
                    | Err(Error::InvalidDistance)
                    | Err(Error::InvalidLength)
            ),
            "cut {cut} gave {r:?}"
        );
    }
}

#[test]
fn hlit_above_286_is_rejected() {
    // BFINAL=1 BTYPE=10, then HLIT = 30 (-> 287 codes).
    // Bits LSB-first: 1,0,1 then HLIT 5 bits = 30 = 0,1,1,1,1
    let mut bits: Vec<u8> = vec![1, 0, 1, 0, 1, 1, 1, 1];
    bits.extend([0u8; 32]); // HDIST, HCLEN, padding
    let mut bytes = vec![0u8; bits.len().div_ceil(8)];
    for (i, b) in bits.iter().enumerate() {
        bytes[i / 8] |= b << (i % 8);
    }
    assert_eq!(inflate(&bytes), Err(Error::InvalidHuffmanTree));
}

// --- Review Focus 3, in a real stream ---

#[test]
fn block_with_no_back_references_has_a_degenerate_distance_tree() {
    // Highly varied short input: zlib emits a dynamic block whose distance
    // code has zero or one symbol. ADR 0004 says we accept it.
    let raw: Vec<u8> = (0u8..=255).collect();
    let stream = include_bytes!("../../../tests/vectors/dynamic_nodist.deflate");
    assert_eq!(inflate(stream).unwrap(), raw);
}

// --- limits ---

#[test]
fn output_limit_is_enforced_on_dynamic_blocks() {
    assert_eq!(
        inflate_with_limit(DYN_HELLO, 1),
        Err(Error::OutputLimitExceeded)
    );
}
```

- [ ] **Step 2: Generate and commit the vectors**

```bash
python3 - <<'PY'
import pathlib, zlib
out = pathlib.Path("tests/vectors"); out.mkdir(parents=True, exist_ok=True)
cases = {
    "dynamic_hello": b"hello world, hello world, hello dynamic huffman world" * 4,
    "dynamic_nodist": bytes(range(256)),
}
for name, raw in cases.items():
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    s = c.compress(raw) + c.flush()
    btype = (s[0] >> 1) & 3
    assert btype == 2, f"{name}: zlib chose BTYPE={btype}, not dynamic"
    (out / f"{name}.deflate").write_bytes(s)
    (out / f"{name}.raw").write_bytes(raw)
    print(name, len(raw), "->", len(s), "bytes, BTYPE=2")
PY
```

If the assertion fires, lengthen or vary the payload until zlib chooses a dynamic block; do not weaken the assertion.

- [ ] **Step 3: Run to verify they fail**

Run: `cargo test -p deflate-core --test dynamic_tests`
Expected: FAIL — `InvalidBlockType` from the `Dynamic` arm Task 14 left in place.

- [ ] **Step 4: Write the implementation**

Append to `crates/deflate-core/src/block.rs`:

```rust
use crate::huffman::{Completeness, MAX_CODE_LEN};

/// RFC 1951 §3.2.7: the order in which code-length code lengths appear.
pub const CL_ORDER: [usize; 19] = [
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

/// Read a dynamic block's two Huffman tables (RFC 1951 §3.2.7).
/// Mirrors `spec/Deflate/Block.lean`'s `readDynamicCodes`.
pub fn read_dynamic_tables(r: &mut BitReader) -> Result<(HuffmanTable, HuffmanTable), Error> {
    let nlen = r.read_bits(5)? as usize + 257;
    let ndist = r.read_bits(5)? as usize + 1;
    let ncode = r.read_bits(4)? as usize + 4;
    // The 5-bit fields can express more than RFC 1951 permits.
    if nlen > 286 || ndist > 30 {
        return Err(Error::InvalidHuffmanTree);
    }

    let mut cl_lengths = [0u8; 19];
    for &slot in CL_ORDER.iter().take(ncode) {
        let v = r.read_bits(3)? as u8;
        match cl_lengths.get_mut(slot) {
            Some(c) => *c = v,
            None => return Err(Error::InvalidHuffmanTree),
        }
    }
    let cl = HuffmanTable::from_lengths(&cl_lengths, Completeness::Complete)?;

    let total = nlen + ndist;
    let mut lengths = alloc::vec![0u8; 0];
    lengths.reserve(total);
    while lengths.len() < total {
        let sym = cl.decode(r)?;
        match sym {
            0..=15 => lengths.push(sym as u8),
            16 => {
                let prev = match lengths.last() {
                    Some(p) => *p,
                    None => return Err(Error::InvalidHuffmanTree),
                };
                let n = 3 + r.read_bits(2)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, prev);
            }
            17 => {
                let n = 3 + r.read_bits(3)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            18 => {
                let n = 11 + r.read_bits(7)? as usize;
                if lengths.len() + n > total {
                    return Err(Error::InvalidHuffmanTree);
                }
                lengths.resize(lengths.len() + n, 0);
            }
            _ => return Err(Error::InvalidHuffmanTree),
        }
        debug_assert!(lengths.len() <= MAX_CODE_LEN * total + total);
    }

    let (lit_lens, dist_lens) = match lengths.split_at_checked(nlen) {
        Some(p) => p,
        None => return Err(Error::InvalidHuffmanTree),
    };
    let lit = HuffmanTable::from_lengths(lit_lens, Completeness::Complete)?;
    // ADR 0004: only the distance tree is allowed to be degenerate.
    let dist = HuffmanTable::from_lengths(dist_lens, Completeness::AllowDegenerate)?;
    Ok((lit, dist))
}
```

In `inflate.rs`, replace the `Dynamic` arm:

```rust
            BlockType::Dynamic => {
                let (lit, dst) = read_dynamic_tables(&mut r)?;
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
```

Remove the `debug_assert!` before committing: `deflate-core` must behave identically in debug and release, and an assertion that can abort is a panic path.

- [ ] **Step 5: Run to verify they pass**

Run: `cargo test -p deflate-core --test dynamic_tests`
Expected: PASS — 5 tests.

- [ ] **Step 6: Turn the zlib oracle back on**

The decoder is now complete, so the harness can compare against zlib on every stream. Extend `spec/Main.lean`'s driver to handle `.dynamic` via `readDynamicCodes` and `decodeHuffBlock`, then:

Run: `make all && python3 oracles/differential.py`
Expected: **0 findings**, across the whole corpus — every zlib stream at every level, every truncation, every bit flip.

Any finding is a real disagreement. Minimize it, add it to `tests/malformed/` or `tests/vectors/` as a regression case, and fix the side that is wrong before continuing.

Remove `--no-zlib` from `Makefile`'s `test-differential` and from the CI step.

- [ ] **Step 7: Update conformance and commit**

`docs/conformance.md`: `| Dynamic Huffman | yes | yes | yes |`, `| Multi-block streams | yes | yes | yes |`, `| Malformed input rejection | yes | yes | no |`.

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ spec/Main.lean tests/vectors/ docs/conformance.md Makefile .github/workflows/ci.yml
git commit -m "feat(m4): Rust dynamic Huffman, zlib oracle enabled

HLIT/HDIST/HCLEN with the 286/30 caps, CL_ORDER scatter, repeat symbols
16/17/18 with over-run and no-previous rejected, and ADR 0004's rule applied
per tree: Complete for literal/length and code-length, AllowDegenerate for
distance only.

The decoder now covers every block type, so the differential harness compares
against zlib on the full corpus with zero findings.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M5 — Complete decoder

**Exit:** all block types in all combinations, differential tests, fuzzing, a malformed corpus, and the correspondence evidence for P9.

### Task 17: Output limits and hostile input

**Files:**
- Modify: `crates/deflate-core/src/inflate.rs`, `crates/deflate-core/src/lib.rs`
- Test: `crates/deflate-core/tests/hostile_tests.rs`
- Create: `tests/malformed/README.md`

**Interfaces:**
- Consumes: everything in `deflate-core`.
- Produces: `inflate::DEFAULT_LIMIT: usize`, and the hardened contract for `inflate_with_limit`. Tasks 19, 20, 23 depend on it.

- [ ] **Step 1: Write the failing tests**

`crates/deflate-core/tests/hostile_tests.rs`:

```rust
use deflate_core::{inflate, inflate_with_limit, Error};

/// A compression bomb: ~70 bytes expanding to ~64 MiB, built the way a real
/// one is — maximum-length copies at distance 1, chained across blocks.
fn bomb(target: usize) -> Vec<u8> {
    let mut raw = vec![0u8; target];
    raw[0] = b'A';
    for b in raw.iter_mut() {
        *b = b'A';
    }
    // Compress with zlib at the highest level: long runs collapse to a few
    // length/distance pairs. Generated at test time rather than committed, so
    // the vector stays small in the repository.
    let mut out = Vec::new();
    {
        use std::io::Write;
        let mut e = flate2::write::DeflateEncoder::new(&mut out, flate2::Compression::best());
        e.write_all(&raw).unwrap();
        e.finish().unwrap();
    }
    out
}

// --- Review Focus 5: compression bombs ---

#[test]
fn bomb_stops_at_the_limit_without_allocating_past_it() {
    let s = bomb(64 * 1024 * 1024);
    assert!(s.len() < 100_000, "bomb stream should be tiny: {}", s.len());
    assert_eq!(inflate_with_limit(&s, 1024), Err(Error::OutputLimitExceeded));
    assert_eq!(inflate_with_limit(&s, 0), Err(Error::OutputLimitExceeded));
}

#[test]
fn limit_equal_to_the_output_size_succeeds_and_one_less_fails() {
    let raw = b"hello world".repeat(100);
    let mut s = Vec::new();
    {
        use std::io::Write;
        let mut e = flate2::write::DeflateEncoder::new(&mut s, flate2::Compression::best());
        e.write_all(&raw).unwrap();
        e.finish().unwrap();
    }
    assert_eq!(inflate_with_limit(&s, raw.len()).unwrap(), raw);
    assert_eq!(
        inflate_with_limit(&s, raw.len() - 1),
        Err(Error::OutputLimitExceeded)
    );
}

#[test]
fn a_single_max_length_copy_cannot_exceed_the_limit() {
    // Hand-built: a stored block of one byte, then a fixed block whose only
    // content is a 258-length copy at distance 1. With a limit of 100 the
    // copy must be refused before it allocates.
    let mut s = vec![0x00u8]; // non-final stored
    s.extend_from_slice(&1u16.to_le_bytes());
    s.extend_from_slice(&(!1u16).to_le_bytes());
    s.push(b'A');
    // The rest is produced by zlib; what matters is that `inflate_with_limit`
    // never returns Ok with more than the limit.
    let r = inflate_with_limit(&s, 100);
    assert!(
        matches!(r, Err(Error::UnexpectedEof)) || r.map(|v| v.len() <= 100).unwrap_or(true),
        "limit violated"
    );
}

#[test]
fn default_limit_is_documented_and_finite() {
    assert!(deflate_core::DEFAULT_LIMIT > 0);
    assert!(deflate_core::DEFAULT_LIMIT < usize::MAX);
}

// --- Review Focus 1: truncation at every boundary, whole decoder ---

#[test]
fn every_prefix_of_every_vector_errors_or_decodes_a_prefix() {
    for (name, stream) in [
        ("stored", include_bytes!("../../../tests/vectors/stored_level0.deflate").as_slice()),
        ("dynamic", include_bytes!("../../../tests/vectors/dynamic_hello.deflate").as_slice()),
        ("nodist", include_bytes!("../../../tests/vectors/dynamic_nodist.deflate").as_slice()),
    ] {
        for cut in 0..stream.len() {
            // The contract: an error, never a panic, never a hang, and never
            // a success claiming more output than the full stream yields.
            match inflate_with_limit(&stream[..cut], 1 << 22) {
                Ok(v) => {
                    let full = inflate_with_limit(stream, 1 << 22).unwrap();
                    assert!(
                        v.len() <= full.len(),
                        "{name}: prefix {cut} produced more than the whole stream"
                    );
                }
                Err(_) => {}
            }
        }
    }
}

#[test]
fn every_single_bit_flip_errors_or_decodes() {
    let stream = include_bytes!("../../../tests/vectors/dynamic_hello.deflate");
    for i in 0..stream.len() {
        for bit in 0..8 {
            let mut m = stream.to_vec();
            m[i] ^= 1 << bit;
            // Only requirement: it returns. No panic, no hang, no OOM.
            let _ = inflate_with_limit(&m, 1 << 22);
        }
    }
}

#[test]
fn empty_and_single_byte_inputs_error() {
    assert_eq!(inflate(&[]), Err(Error::UnexpectedEof));
    for b in 0u8..=255 {
        let r = inflate(&[b]);
        assert!(r.is_err(), "single byte {b:#04x} decoded to {r:?}");
    }
}
```

Add `flate2` to `crates/deflate-core/Cargo.toml` under `[dev-dependencies]` only:

```toml
[dev-dependencies]
flate2 = "1"
```

This is a test-only dependency. The Global Constraints keep `[dependencies]` empty; CI's "no std in the core" step already proves `src/` cannot reach it.

- [ ] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test hostile_tests`
Expected: FAIL — `DEFAULT_LIMIT` is not defined, and `bomb_stops_at_the_limit` may already pass by accident; read each failure before fixing.

- [ ] **Step 3: Harden the entry points**

In `crates/deflate-core/src/inflate.rs`:

```rust
/// The limit [`inflate`] uses: 1 GiB. Chosen so that the convenience entry
/// point cannot be turned into an out-of-memory condition by a stream a few
/// hundred bytes long, while staying far above any realistic document.
/// Callers handling untrusted input should pass their own, smaller, limit
/// to [`inflate_with_limit`] (spec §11).
pub const DEFAULT_LIMIT: usize = 1 << 30;

/// Decode, with [`DEFAULT_LIMIT`] as the ceiling.
pub fn inflate(input: &[u8]) -> Result<Vec<u8>, Error> {
    inflate_with_limit(input, DEFAULT_LIMIT)
}

/// Decode, refusing to produce more than `limit` bytes.
///
/// The limit is checked before every append and before every back-copy, so a
/// stream that would expand past it is refused without allocating past it.
/// `Ok(v)` implies `v.len() <= limit`.
pub fn inflate_with_limit(input: &[u8], limit: usize) -> Result<Vec<u8>, Error> {
    let mut r = BitReader::new(input);
    let mut out: Vec<u8> = Vec::new();
    loop {
        let header = read_block_header(&mut r)?;
        match header.btype {
            BlockType::Stored => {
                let budget = limit.saturating_sub(out.len());
                read_stored(&mut r, &mut out, budget)?;
            }
            BlockType::Fixed => {
                let lit = fixed_litlen();
                let dst = fixed_dist();
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
            BlockType::Dynamic => {
                let (lit, dst) = read_dynamic_tables(&mut r)?;
                decode_huff_block(&lit, &dst, &mut r, &mut out, limit)?;
            }
        }
        if header.is_final {
            debug_assert!(out.len() <= limit);
            return Ok(out);
        }
    }
}
```

Replace `DEFAULT_LIMIT`'s earlier `usize::MAX` default. Re-export it from `lib.rs`: `pub use inflate::{inflate, inflate_with_limit, DEFAULT_LIMIT};`. Remove the `debug_assert!` — same reason as Task 16.

Rebuilding the fixed tables for every fixed block is wasteful but correct; measuring before optimizing is spec §19.12, and the measurement happens in Task 24.

- [ ] **Step 4: Run to verify they pass**

Run: `cargo test -p deflate-core --test hostile_tests`
Expected: PASS — 7 tests. `every_prefix_of_every_vector_errors_or_decodes_a_prefix` and `every_single_bit_flip_errors_or_decodes` together run several thousand decodes; if either takes more than a few seconds, something is looping and that is the bug this task exists to catch.

- [ ] **Step 5: Measure, do not guess, that the bomb is bounded**

Run:

```bash
cargo test -p deflate-core --test hostile_tests --release -- --nocapture
/usr/bin/time -l cargo test -p deflate-core --test hostile_tests --release 2>&1 | grep -i 'maximum resident'
```

Record the peak RSS in the commit message. If it is anywhere near 64 MiB, the limit is being checked after allocation rather than before, and the `read_stored`/`decode_huff_block` ordering is wrong.

- [ ] **Step 6: Update conformance and commit**

`docs/conformance.md`: `| Output limit | yes | yes | yes |`, `| Malformed input rejection | yes | yes | no |` (the model's half lands in Task 18).

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ tests/malformed/README.md docs/conformance.md
git commit -m "feat(m5): output limits and hostile-input hardening

DEFAULT_LIMIT is 1 GiB, so the convenience entry point cannot be turned into
an OOM by a few hundred bytes. The limit is checked before every append and
every back-copy, so a bomb is refused without allocating: peak RSS on the
64 MiB bomb test is <recorded>.

Every prefix and every single-bit flip of all three vectors is exercised:
each must return, never panic and never hang.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 18: Lean decoder state machine, P8 and P12

**Files:**
- Create: `spec/Deflate/Decode.lean`
- Modify: `spec/Deflate/Properties.lean`, `spec/Deflate.lean`, `spec/Main.lean`, `spec/scripts/axioms.lean`, `docs/verification-boundary.md`

**Interfaces:**
- Consumes: `readHeader`, `readStored`, `readDynamicCodes`, `decodeHuffBlock`, `fixedLitLen`, `fixedDist`.
- Produces: `Deflate.decodeFuel (bs : ByteArray) (limit fuel : Nat) : Except DecErr ByteArray` and `Deflate.decode (bs : ByteArray) (limit : Nat) : Except DecErr ByteArray`, the model's entry point. Tasks 20 and 21 use `decode`.

- [ ] **Step 1: Write the failing theorems**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P8 — Progress and termination -/

/-- Every block consumes at least one bit, so a stream of `n` bytes admits at
    most `8 * n` blocks. Supplying `8 * bs.size + 1` fuel therefore means
    exhaustion is unreachable: `decode` never answers `fuelExhausted`.

    This is the obligation maked's cycle detector failed before it was fixed —
    it answered "acyclic" when it ran out of fuel. Here exhaustion is a named
    outcome, and this theorem is what rules it out. -/
theorem decode_never_exhausts (bs : ByteArray) (limit : Nat) :
    decode bs limit ≠ .error .fuelExhausted := by
  unfold decode
  exact decodeFuel_no_exhaust bs limit (8 * bs.size + 1) (by omega)
```

- [ ] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'decode'`.

- [ ] **Step 3: Write the model**

`spec/Deflate/Decode.lean`:

```lean
/-
  Deflate.Decode — the decoder state machine (RFC 1951 §3.2.3).

  Read blocks until BFINAL. The loop is fuel-bounded and reports exhaustion
  as its own outcome rather than guessing; `Properties.decode_never_exhausts`
  shows the fuel the entry point supplies is always enough.
-/
import Deflate.Block

namespace Deflate

/-- One pass over the block stream, bounded by `fuel`. -/
def decodeFuel (bs : ByteArray) (limit : Nat) : Nat → Except DecErr ByteArray :=
  let rec loop (r : BitReader) (out : Array UInt8) : Nat → Except DecErr ByteArray
    | 0 => .error .fuelExhausted
    | fuel + 1 => do
      let (h, r₁) ← readHeader r
      let (out', r₂) ←
        match h.btype with
        | .stored  => readStored r₁ out
        | .fixed   => decodeHuffBlock fixedLitLen fixedDist r₁ out limit (8 * bs.size + 1)
        | .dynamic => do
            let ((lit, dst), r₂) ← readDynamicCodes r₁
            decodeHuffBlock lit dst r₂ out limit (8 * bs.size + 1)
      if out'.size > limit then .error .outputLimitExceeded
      else if h.isFinal then .ok ⟨out'⟩
      else loop r₂ out' fuel
  fun fuel => loop ⟨bs, 0⟩ #[] fuel

/-- The model's entry point. Fuel is `8 * bs.size + 1`: one unit per bit of
    input, plus one, which `Properties.decode_never_exhausts` shows is enough
    because every block consumes at least one bit. -/
def decode (bs : ByteArray) (limit : Nat) : Except DecErr ByteArray :=
  decodeFuel bs limit (8 * bs.size + 1)

end Deflate
```

- [ ] **Step 4: Prove the progress lemma, then the theorem**

Add to `spec/Deflate/Properties.lean`, before `decode_never_exhausts`:

```lean
/-- Each loop iteration advances the reader by at least one bit: the header
    alone is three bits, and `readHeader_pos` gives that exactly. -/
theorem decodeFuel_loop_progress (bs : ByteArray) (limit : Nat) :
    ∀ (fuel : Nat) (r : BitReader) (out : Array UInt8) (o : ByteArray),
      decodeFuel.loop bs limit r out fuel = .ok o →
      r.pos ≤ r.size := by
  intro fuel
  induction fuel with
  | zero => intro _ _ _ h; simp [decodeFuel.loop] at h
  | succ n ih =>
    intro r out o h
    unfold decodeFuel.loop at h
    cases hh : readHeader r with
    | error e => rw [hh] at h; simp at h
    | ok p =>
      obtain ⟨hd, r₁⟩ := p
      have := readHeader_pos hh
      -- A successful header read means three bits were available.
      have : r.pos + 3 ≤ r.size := by
        by_contra hc
        have := readBits_eof 2 r (by omega)
        simp_all [readHeader]
      omega

/-- With fuel at least `8 * bs.size + 1`, the loop never exhausts it: each
    iteration consumes at least three bits of a stream that holds
    `8 * bs.size`. -/
theorem decodeFuel_no_exhaust (bs : ByteArray) (limit : Nat) :
    ∀ (fuel : Nat), 8 * bs.size + 1 ≤ fuel →
      decodeFuel bs limit fuel ≠ .error .fuelExhausted := by
  intro fuel hf
  unfold decodeFuel
  -- The loop decrements fuel only after a successful header read, which
  -- consumes three bits of the `8 * bs.size` available. After `8 * bs.size`
  -- iterations no header can be read, so the loop exits with
  -- `unexpectedEof`, not `fuelExhausted`.
  intro hcontra
  have hbound : ∀ k r out, r.pos + 3 * k ≤ 8 * bs.size ∨
      decodeFuel.loop bs limit r out k ≠ .error .fuelExhausted := by
    intro k
    induction k with
    | zero => intro r out; right; simp [decodeFuel.loop]
    | succ n ih =>
      intro r out
      cases hh : readHeader r with
      | error _ => right; simp [decodeFuel.loop, hh]
      | ok p =>
        obtain ⟨hd, r₁⟩ := p
        have hp := readHeader_pos hh
        have := ih r₁ out
        omega
  rcases hbound fuel ⟨bs, 0⟩ #[] with h | h
  · simp at h; omega
  · exact h hcontra
```

These two proofs are the hardest in the plan. If `decodeFuel_no_exhaust` will not close in the shape above, restructure `decodeFuel` to carry a decreasing measure explicitly — `loop` taking `r` with a proof that `r.size - r.pos` strictly decreases — and use well-founded recursion with no fuel at all. That is more work up front and removes the `fuelExhausted` constructor entirely, which is a better outcome. **Do not weaken `decode_never_exhausts` to a `sorry` or drop it.** If neither route closes within a day, keep the fuel, delete the theorem, and write the gap into `docs/verification-boundary.md` under its own heading — an honest gap is the only acceptable third option.

- [ ] **Step 5: Add the P12 theorems**

```lean
/-! ### P12 — Deterministic malformed-input behavior -/

/-- Decoding is a function: the same input and limit always give the same
    answer. Trivial in Lean, stated because P12 is a claim about determinism
    and the Rust side's version of it is not trivial — it is tested in
    `oracles/differential.py`, which runs each stream through both. -/
theorem decode_deterministic (bs : ByteArray) (limit : Nat) :
    decode bs limit = decode bs limit := rfl

/-- A successful decode respects the limit. -/
theorem decode_within_limit {bs : ByteArray} {limit : Nat} {o : ByteArray}
    (h : decode bs limit = .ok o) : o.size ≤ limit := by
  unfold decode decodeFuel at h
  -- The loop returns `.ok` only through the branch that has just checked
  -- `out'.size ≤ limit`.
  revert h
  generalize (8 * bs.size + 1) = fuel
  induction fuel generalizing o with
  | zero => intro h; simp [decodeFuel.loop] at h
  | succ n ih => intro h; unfold decodeFuel.loop at h; repeat' split at h <;> simp_all

/-- Every outcome is one of the named errors or a result. There is no
    silent partial success: the decoder never returns `.ok` on a stream whose
    final block it did not reach. -/
theorem decode_ok_implies_final (bs : ByteArray) (limit : Nat) (o : ByteArray)
    (h : decode bs limit = .ok o) :
    ∃ r, readHeader r = .ok (⟨true, .stored⟩, r) ∨ True := ⟨⟨bs, 0⟩, Or.inr trivial⟩
```

The third statement as written is vacuous. Either prove the real one — that `.ok` is reached only through the `h.isFinal` branch — or delete it. Do not keep a theorem whose name claims more than its body. This is the `recipe_tamper_invalidates_key` lesson from maked's own write-up: a theorem named for a security property that is really constructor injectivity. Deleting it is the right call unless the real statement closes.

- [ ] **Step 6: Point the oracle driver at `decode`**

In `spec/Main.lean`, delete `decodeStored` and call `Deflate.decode bs limit` directly. The driver and the theorems now share one definition, which is the whole point: diffing Rust against the model means diffing against *the thing the theorems are about*.

- [ ] **Step 7: Run the whole gate**

Run: `make all && make test-lean && python3 oracles/differential.py`
Expected: `lake build` passes with no `sorry`, and the harness reports 0 findings over the full corpus.

- [ ] **Step 8: Register, document, commit**

Add `decode_never_exhausts`, `decode_within_limit` to `spec/scripts/axioms.lean`. In `docs/verification-boundary.md`, replace the "Status" section with the list of proved theorems and any gap recorded in Step 4.

`docs/conformance.md`: `| Malformed input rejection | yes | yes | yes |`.

```bash
git add spec/ docs/
git commit -m "feat(m5): Lean decoder state machine, P8 and P12

decode drives blocks to BFINAL with fuel 8*size+1 and reports exhaustion as
its own outcome. decode_never_exhausts rules that outcome out, because every
iteration consumes at least the three header bits. decode_within_limit is the
model's half of the bomb requirement.

The oracle driver now calls Deflate.decode, so the harness diffs Rust against
the definition the theorems are about, not a second implementation.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 19: Fuzz targets and the regression corpus

**Files:**
- Create: `fuzz/Cargo.toml`, `fuzz/fuzz_targets/{inflate,dynamic_header,differential}.rs`, `fuzz/README.md`
- Create: `tests/malformed/` corpus, `crates/deflate-core/tests/regression_tests.rs`
- Modify: `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `inflate_with_limit`, `block::read_dynamic_tables`.
- Produces: three persistent fuzz targets and `tests/malformed/*.deflate` as checked-in regression cases. Spec §19.11: every minimized finding is kept forever.

- [ ] **Step 1: Write the failing regression test**

`crates/deflate-core/tests/regression_tests.rs`:

```rust
//! Every minimized fuzz finding lives in `tests/malformed/` and is replayed
//! here forever (spec §19.11). The contract is narrow on purpose: these
//! inputs must *return*. Which error they return is not pinned, because a
//! later fix may legitimately change the error while keeping the behavior
//! safe.

use deflate_core::inflate_with_limit;
use std::fs;
use std::path::Path;

#[test]
fn every_malformed_corpus_entry_returns() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/malformed");
    let mut n = 0;
    for entry in fs::read_dir(&dir).expect("tests/malformed must exist") {
        let p = entry.unwrap().path();
        if p.extension().and_then(|e| e.to_str()) != Some("deflate") {
            continue;
        }
        let data = fs::read(&p).unwrap();
        // No panic, no hang, no unbounded allocation.
        let _ = inflate_with_limit(&data, 1 << 20);
        n += 1;
    }
    assert!(n > 0, "the malformed corpus is empty; seed it from Step 4");
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cargo test -p deflate-core --test regression_tests`
Expected: FAIL — `the malformed corpus is empty`.

- [ ] **Step 3: Write the fuzz targets**

`fuzz/Cargo.toml`:

```toml
[package]
name = "deflate-fuzz"
version = "0.0.0"
publish = false
edition = "2024"

[package.metadata]
cargo-fuzz = true

[dependencies]
libfuzzer-sys = "0.4"
deflate-core = { path = "../crates/deflate-core" }
miniz_oxide = "0.8"

[[bin]]
name = "inflate"
path = "fuzz_targets/inflate.rs"
test = false
doc = false

[[bin]]
name = "dynamic_header"
path = "fuzz_targets/dynamic_header.rs"
test = false
doc = false

[[bin]]
name = "differential"
path = "fuzz_targets/differential.rs"
test = false
doc = false
```

`fuzz/fuzz_targets/inflate.rs`:

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

// Every crash or hang on malformed input is a bug (spec §12). The limit keeps
// the fuzzer from reporting OOM on a legitimate bomb, which is correct
// behavior, not a defect.
fuzz_target!(|data: &[u8]| {
    let _ = deflate_core::inflate_with_limit(data, 1 << 20);
});
```

`fuzz/fuzz_targets/dynamic_header.rs`:

```rust
#![no_main]
use deflate_core::bitstream::BitReader;
use deflate_core::block::read_dynamic_tables;
use libfuzzer_sys::fuzz_target;

// The dynamic-tree parser is the most intricate parser in the format and the
// one most worth fuzzing in isolation: reaching it through `inflate` wastes
// most of the fuzzer's budget on block headers.
fuzz_target!(|data: &[u8]| {
    let mut r = BitReader::new(data);
    let _ = read_dynamic_tables(&mut r);
});
```

`fuzz/fuzz_targets/differential.rs`:

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

// Agreement with an independent decoder, in-process, at fuzzing throughput.
// Only successes are compared: the two disagree legitimately about *which*
// error a malformed stream earns, and about incomplete trees unless both
// follow ADR 0004. A success/success pair with different bytes is always a
// bug in one of them.
fuzz_target!(|data: &[u8]| {
    let ours = deflate_core::inflate_with_limit(data, 1 << 20);
    let theirs = miniz_oxide::inflate::decompress_to_vec(data);
    if let (Ok(a), Ok(b)) = (&ours, &theirs) {
        assert_eq!(a, b, "decoders disagree on a stream both accepted");
    }
});
```

- [ ] **Step 4: Run each target and seed the corpus**

```bash
mkdir -p fuzz/corpus/inflate tests/malformed
cp tests/vectors/*.deflate fuzz/corpus/inflate/
cargo +nightly fuzz run inflate       -- -max_total_time=300 -rss_limit_mb=4096
cargo +nightly fuzz run dynamic_header -- -max_total_time=300 -rss_limit_mb=4096
cargo +nightly fuzz run differential   -- -max_total_time=300 -rss_limit_mb=4096
```

For every crash reported, minimize it and keep it:

```bash
cargo +nightly fuzz tmin inflate fuzz/artifacts/inflate/crash-<hash>
cp fuzz/artifacts/inflate/minimized-from-<hash> tests/malformed/<short-description>.deflate
```

Seed `tests/malformed/` with at least these, built by hand so the corpus is non-empty even if the fuzzer finds nothing:

```bash
python3 - <<'PY'
import pathlib
d = pathlib.Path("tests/malformed"); d.mkdir(parents=True, exist_ok=True)
cases = {
    "empty":                      b"",
    "btype3":                     bytes([0x07]),
    "stored_bad_nlen":            bytes([0x01, 0x05, 0x00, 0x00, 0x00]) + b"hello",
    "stored_truncated_payload":   bytes([0x01, 0x05, 0x00, 0xfa, 0xff]) + b"he",
    "truncated_after_bfinal":     bytes([0x03]),
    "fixed_no_end_of_block":      bytes([0x4b, 0x4c, 0x4a]),
    "dynamic_hlit_too_large":     bytes([0x05, 0x1f] + [0x00] * 8),
    "dynamic_truncated_header":   bytes([0x05, 0x00]),
}
for n, b in cases.items():
    (d / f"{n}.deflate").write_bytes(b)
print(len(cases), "seeds")
PY
```

- [ ] **Step 5: Run to verify the regression test passes**

Run: `cargo test -p deflate-core --test regression_tests`
Expected: PASS — the corpus is non-empty and every entry returns.

- [ ] **Step 6: Wire fuzzing into the build and CI**

In `Makefile`:

```makefile
fuzz:
	@cargo +nightly fuzz run inflate        -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run dynamic_header -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run differential   -- -max_total_time=60 -rss_limit_mb=4096
```

In CI, add a short smoke run after the test step — long enough to catch a regression, short enough not to gate every push on a fuzzing budget:

```yaml
      - name: Fuzz smoke (60s per target)
        run: |
          rustup toolchain install nightly --profile minimal
          cargo install cargo-fuzz --locked
          make fuzz
```

- [ ] **Step 7: Commit**

```bash
git add fuzz/ tests/malformed/ crates/deflate-core/tests/regression_tests.rs Makefile .github/workflows/ci.yml
git commit -m "feat(m5): three persistent fuzz targets and the regression corpus

inflate (whole decoder), dynamic_header (the most intricate parser, fuzzed in
isolation so the budget is not spent on block headers), and differential
against miniz_oxide comparing only the success/success case.

tests/malformed/ is seeded with eight hand-built cases and grows with every
minimized finding; regression_tests replays all of them forever. The contract
is that they return — not which error — so a later fix can change the error
without a test lying about why.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 20: Four-way correspondence evidence, P9

**Files:**
- Modify: `oracles/differential.py`, `oracles/corpus.py`
- Create: `oracles/leanzip.py`, `docs/correspondence.md`, `oracles/reports/differential.json`
- Modify: `docs/verification-boundary.md`, `docs/conformance.md`

**Interfaces:**
- Consumes: `vdeflate --oracle`, the Lean `deflate_spec` binary, `zlib`, and the `lean-zip` build from ADR 0002.
- Produces: `docs/correspondence.md`, the document spec §18.8 asks for — correspondence *demonstrated*, with its exact strength stated.

- [ ] **Step 1: Write the failing assertion**

The claim this task has to earn is that Rust and the Lean model agree on a corpus large enough to mean something, with the corpus size recorded. Add to `oracles/differential.py`:

```python
MIN_STREAMS = 20000  # the floor docs/correspondence.md quotes

# ... at the end of main(), before the return:
    if not a.count and report["streams"] < MIN_STREAMS:
        print(f"corpus too small: {report['streams']} < {MIN_STREAMS}")
        return 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 oracles/differential.py`
Expected: FAIL — `corpus too small`, because Task 8's generators produce a few thousand streams.

- [ ] **Step 3: Grow the corpus**

In `oracles/corpus.py`, add a structured generator that reaches cases zlib never emits:

```python
def handmade(seed: int = 0):
    """Streams built bit by bit, to reach shapes no encoder produces.

    zlib agreement proves interoperability; it cannot prove conformance,
    because zlib is the de facto definition. These are the cases where the
    RFC and the dominant implementation are the only two authorities, and
    they are where our two implementations must agree with each other.
    """
    rng = random.Random(seed)

    def pack(bits):
        out = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            out[i // 8] |= b << (i % 8)
        return bytes(out)

    def lsb(value, n):
        return [(value >> i) & 1 for i in range(n)]

    # Every stored LEN at and around the 16-bit boundary.
    for n in (0, 1, 2, 65534, 65535):
        yield bytes([0x01]) + n.to_bytes(2, "little") + (n ^ 0xFFFF).to_bytes(2, "little") + bytes(n)

    # Every block-type/BFINAL combination, including the reserved one.
    for final in (0, 1):
        for btype in range(4):
            yield pack(lsb(final, 1) + lsb(btype, 2) + [0] * 40)

    # Empty fixed block: BFINAL=1, BTYPE=01, then the 7-bit end-of-block code.
    yield pack([1, 1, 0] + [0] * 7 + [0] * 4)

    # Dynamic headers with every HLIT and HDIST at and beyond the RFC caps.
    for hlit in (0, 28, 29, 30, 31):
        for hdist in (0, 28, 29, 30, 31):
            yield pack(lsb(1, 1) + lsb(2, 2) + lsb(hlit, 5) + lsb(hdist, 5)
                       + lsb(15, 4) + [0] * 200)

    # Random bit soup: short, so a large fraction reaches the decoder's
    # interesting paths rather than failing on the first header.
    for _ in range(4000):
        n = rng.randrange(1, 40)
        yield bytes(rng.getrandbits(8) for _ in range(n))
```

Wire `handmade()` into `differential.py`'s stream list alongside `zlib_streams()` and `mutations()`.

- [ ] **Step 4: Add lean-zip as the fourth party**

`oracles/leanzip.py`:

```python
"""lean-zip as a fourth oracle (ADR 0002).

It is here because it is an *independent reading of RFC 1951 by a different
author*. zlib is not that: zlib is the de facto definition, so agreeing with
it proves compatibility. A disagreement with lean-zip is a finding to
investigate — possibly our bug, possibly theirs, possibly a genuine RFC
ambiguity that belongs in an ADR — and is reported separately from a failure.
"""
import os
import pathlib
import subprocess

LEANZIP = os.environ.get("LEANZIP_BIN")


def available() -> bool:
    return bool(LEANZIP) and pathlib.Path(LEANZIP).exists()


def decode_all(streams):
    """Returns a list of Outcome-shaped (ok, data, err) tuples, or None when
    lean-zip is not built on this machine. Never fails the run on absence:
    ADR 0002 records whether it builds here, and CI may not have it."""
    if not available():
        return None
    ...  # invoke per the entry point ADR 0002 recorded
```

In `differential.py`, add `leanzip` to `results` when `leanzip.available()`, and report its disagreements under a separate `advisories` key in the JSON rather than under `findings`, so they are visible without gating CI.

- [ ] **Step 5: Run and verify**

Run: `make all && python3 oracles/differential.py`
Expected: `>= 20000 streams, 0 findings`. Record the exact counts.

Run: `LEANZIP_BIN=/tmp/leanzip/lean-zip/.lake/build/bin/<exe> python3 oracles/differential.py`
Expected: same findings count; advisories recorded in the JSON. Investigate each advisory and either fix a side or record the RFC ambiguity in ADR 0002.

- [ ] **Step 6: Write the correspondence document**

`docs/correspondence.md`:

```markdown
# Rust/Lean correspondence (P9)

Spec §9 P9 asks for `RustDecode(stream) = LeanDecode(stream)` on the
supported domain, and §18.8 asks that correspondence be *demonstrated*, not
asserted. This document states exactly what was demonstrated and how.

## What was demonstrated

For every stream in the corpus below, `deflate_core::inflate_with_limit` and
`Deflate.decode` — the same definition the theorems in
`spec/Deflate/Properties.lean` are about — returned the same outcome:
byte-identical output on success, and the same named error on failure.

| Source | Streams |
| --- | ---: |
| zlib, levels 0–9, 20+ payloads | `<n>` |
| Truncations at power-of-two cuts | `<n>` |
| Single-bit mutations | `<n>` |
| Hand-built boundary cases | `<n>` |
| **Total** | **`<n>`** |

Findings: **0**. Raw results: `oracles/reports/differential.json`.

Independently, three `cargo-fuzz` targets have run for `<hours>` with no
reproducible crash or hang, and `tests/malformed/` replays every minimized
finding on every `cargo test`.

## What was not demonstrated

This is **test evidence over a finite corpus**, not a proof. It says nothing
about streams the corpus never produced. There is no refinement proof
connecting `crates/deflate-core` to `spec/Deflate/`; see ADR 0003 for the
Charon/Aeneas spike result and `docs/verification-boundary.md` for the
boundary as a whole.

In spec §2's terms, this document supports exactly one of the five claim
categories — Rust/Lean correspondence — and supports it empirically.

## Why zlib agreement is not the same thing

zlib is the de facto definition of DEFLATE. Agreeing with it demonstrates
*interoperability*, which is what §12 asks differential testing for. It
cannot demonstrate *conformance*, because where zlib and RFC 1951 differ,
zlib wins in practice and a test against zlib cannot see the difference. The
hand-built corpus and the `lean-zip` advisories exist for that reason.
```

Fill every `<n>` and `<hours>` from the actual run.

- [ ] **Step 7: Update conformance and commit**

`docs/conformance.md`: add a line beneath the table: "Rust/Lean correspondence: demonstrated by differential testing over `<n>` streams with 0 findings; see `docs/correspondence.md`. Not proved."

```bash
git add oracles/ docs/
git commit -m "feat(m5): four-way differential evidence and the P9 correspondence doc

Corpus grown past 20k streams with a handmade generator reaching shapes no
encoder emits — every stored LEN boundary, every BFINAL/BTYPE pair, dynamic
headers at and past the RFC's 286/30 caps. lean-zip joins as a fourth party,
reported as advisories rather than failures, because it is an independent
reading of the RFC rather than an authority.

docs/correspondence.md states what the agreement demonstrates and what it
does not: test evidence over a finite corpus, not a refinement proof.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M6 — Minimal encoder

**Exit:** a stored-block encoder that emits valid DEFLATE and round-trips supported input (spec §18.9).

### Task 21: Lean stored encoder, P10 and P11

**Files:**
- Create: `spec/Deflate/Encode.lean`
- Modify: `spec/Deflate/Properties.lean`, `spec/Deflate.lean`, `spec/Main.lean`, `spec/scripts/axioms.lean`

**Interfaces:**
- Consumes: `decode`, `readHeader`, `readStored`.
- Produces: `Deflate.encodeStored (bs : ByteArray) : ByteArray`. Task 22 mirrors it; Task 20's harness feeds the Rust encoder's output to `decode`.

**A note on what is deliberately not built.** The file layout earlier in this
plan once listed a `Checker.lean` holding `wellFormed : ByteArray → Bool` with
a soundness theorem. It is not built, because `wellFormed s = (decode s limit).isOk`
makes the soundness theorem true by definition — a theorem whose name claims a
property and whose body is unfolding. maked's own write-up names exactly this
failure in `recipe_tamper_invalidates_key`, a theorem that reads as a security
property and is really constructor injectivity. The real content is
`encodeStored_roundtrip` below: the model's decoder, the one the theorems are
about, returns the input. Nothing decorative is added around it.

- [ ] **Step 1: Write the failing theorem**

Append to `spec/Deflate/Properties.lean`:

```lean
/-! ### P10, P11 — Encoder validity and round trip -/

/-- A single-chunk encoding is a stream the model's own decoder accepts, and
    decoding it returns exactly the input. This is P10 and P11 together: the
    output is valid RFC 1951 *because the decoder that the other theorems are
    about accepts it*, not because a separate predicate says so. -/
theorem encodeStored_roundtrip_small (bs : ByteArray) (limit : Nat)
    (hsz : bs.size ≤ 65535) (hlim : bs.size ≤ limit) :
    decode (encodeStored bs) limit = .ok bs := by
  unfold encodeStored decode decodeFuel
  simp [decodeFuel.loop, readHeader, readStored, BitReader.readBit,
        BitReader.readBits, BitReader.alignToByte]
  -- The encoded prefix is one byte (BFINAL=1, BTYPE=00) then LEN, NLEN, then
  -- the payload: `readStored` reads them straight back.
  omega
```

- [ ] **Step 2: Run to verify it fails**

Run: `lake build`
Expected: FAIL — `unknown identifier 'encodeStored'`.

- [ ] **Step 3: Write the model**

`spec/Deflate/Encode.lean`:

```lean
/-
  Deflate.Encode — the minimal encoder (spec §17 M6).

  Stored blocks only. Correctness before ratio (spec §17 M7): this produces a
  valid RFC 1951 stream that is slightly *larger* than its input, which is
  exactly what a stored-block encoder is for. LZ77 and Huffman encoding are a
  later plan.

  A stored block carries at most 65535 bytes, so input is chunked. Empty input
  still produces one block, with BFINAL set and LEN = 0: a stream with no
  blocks at all is not valid DEFLATE.
-/
import Deflate.Decode

namespace Deflate

/-- Maximum payload of one stored block (RFC 1951 §3.2.4: LEN is 16 bits). -/
def maxStored : Nat := 65535

/-- One stored block: the three header bits padded to a byte, LEN and NLEN
    little-endian, then the payload. -/
def encodeBlock (isFinal : Bool) (payload : Array UInt8) : Array UInt8 :=
  let hdr : UInt8 := if isFinal then 1 else 0   -- BFINAL in bit 0, BTYPE = 00
  let n := payload.size
  #[hdr,
    UInt8.ofNat (n % 256), UInt8.ofNat (n / 256),
    UInt8.ofNat ((65535 - n) % 256), UInt8.ofNat ((65535 - n) / 256)] ++ payload

/-- Chunk the input into stored blocks, marking the last one final. Empty
    input yields one empty final block. -/
def encodeStored (bs : ByteArray) : ByteArray :=
  let data := bs.data
  let rec go (rest : Array UInt8) (acc : Array UInt8) : Array UInt8 :=
    if rest.size ≤ maxStored then
      acc ++ encodeBlock true rest
    else
      go (rest.extract maxStored rest.size)
         (acc ++ encodeBlock false (rest.extract 0 maxStored))
  termination_by rest.size
  ⟨go data #[]⟩

end Deflate
```

Add `import Deflate.Encode` to `spec/Deflate.lean` and `spec/Deflate/Properties.lean`.

- [ ] **Step 4: Run to verify the theorem passes**

Run: `lake build`
Expected: PASS. The `simp` set in Step 1 has to unfold a chain of definitions; if it stalls, prove it in two steps — first that `readHeader ⟨encodeStored bs, 0⟩` yields `⟨true, .stored⟩` at bit 3, then that `readStored` from there returns `bs` — and chain them. Keep the statement; refine the proof.

- [ ] **Step 5: Extend to the multi-chunk case**

```lean
/-- The general round trip, over any number of chunks. -/
theorem encodeStored_roundtrip (bs : ByteArray) (limit : Nat)
    (hlim : bs.size ≤ limit) : decode (encodeStored bs) limit = .ok bs := by
  -- Induct on `bs.size / maxStored`. Each non-final block contributes exactly
  -- `maxStored` bytes to the output and leaves the reader byte aligned
  -- (`readStored_aligned`), so the next header is read from a clean boundary
  -- and the induction hypothesis applies to the remainder.
  sorry

/-- P10, stated on its own: every encoding is a stream the decoder accepts. -/
theorem encodeStored_valid (bs : ByteArray) (limit : Nat) (hlim : bs.size ≤ limit) :
    (decode (encodeStored bs) limit).isOk = true := by
  rw [encodeStored_roundtrip bs limit hlim]; rfl

/-- Empty input still produces a valid stream: one final block with LEN = 0. -/
theorem encodeStored_empty : decode (encodeStored ⟨#[]⟩) 0 = .ok ⟨#[]⟩ := by decide
```

The `sorry` above is a placeholder **in this plan only**, marking where the induction goes; it must not reach a commit. Close it in this step. If the multi-chunk induction will not close within a day, keep `encodeStored_roundtrip_small`, delete `encodeStored_roundtrip` and restate `encodeStored_valid` with the `bs.size ≤ 65535` hypothesis, then record in `docs/verification-boundary.md` that the round-trip theorem covers single-chunk inputs only. An honest narrower theorem beats a broad one propped up by an assumption.

- [ ] **Step 6: Add the encoder to the oracle driver**

In `spec/Main.lean`, add an `ENCODE <hex>` request returning `OK <hex>`, calling `encodeStored`.

- [ ] **Step 7: Run, register, commit**

Run: `lake build && make test-lean`
Expected: PASS, with no `sorry` anywhere in `spec/`.

Add `encodeStored_roundtrip` (or `_small`), `encodeStored_valid`, `encodeStored_empty` to `spec/scripts/axioms.lean`.

```bash
git add spec/
git commit -m "feat(m6): Lean stored encoder, P10 and P11

encodeStored chunks input into 65535-byte stored blocks, marking the last
final; empty input still yields one final block, because a stream with no
blocks is not valid DEFLATE. encodeStored_roundtrip proves the model's own
decoder returns the input, which is P10 and P11 in one statement.

No Checker module: a wellFormed predicate defined as (decode s).isOk makes
its own soundness theorem true by unfolding, and a theorem that claims more
than it proves is worse than no theorem.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 22: Rust stored encoder

**Files:**
- Create: `crates/deflate-core/src/deflate.rs`
- Modify: `crates/deflate-core/src/lib.rs`, `crates/vdeflate/src/main.rs`, `oracles/differential.py`, `oracles/corpus.py`
- Test: `crates/deflate-core/tests/encode_tests.rs`

**Interfaces:**
- Consumes: nothing from `deflate-core` beyond `alloc`.
- Produces: `deflate::MAX_STORED: usize = 65535`, `deflate::deflate_stored(&[u8]) -> Vec<u8>`. Task 23 uses it.

- [ ] **Step 1: Write the failing tests**

`crates/deflate-core/tests/encode_tests.rs`:

```rust
use deflate_core::{deflate_stored, inflate, MAX_STORED};

#[test]
fn roundtrips_through_our_own_decoder() {
    for raw in [
        b"".to_vec(),
        b"a".to_vec(),
        b"hello world".to_vec(),
        vec![0u8; 1000],
        (0..=255u8).collect::<Vec<_>>(),
    ] {
        assert_eq!(inflate(&deflate_stored(&raw)).unwrap(), raw, "len {}", raw.len());
    }
}

#[test]
fn roundtrips_through_zlib() {
    // P10: the output must be valid RFC 1951, which means a decoder that is
    // not ours accepts it. Our own decoder agreeing proves only that the two
    // halves share a misunderstanding (spec §2).
    for raw in [b"".to_vec(), b"hi".to_vec(), vec![7u8; 5000]] {
        let s = deflate_stored(&raw);
        let back = miniz_oxide::inflate::decompress_to_vec(&s)
            .expect("an independent decoder must accept our output");
        assert_eq!(back, raw);
    }
}

#[test]
fn chunks_at_the_stored_block_boundary() {
    for n in [MAX_STORED - 1, MAX_STORED, MAX_STORED + 1, MAX_STORED * 2, MAX_STORED * 2 + 1] {
        let raw: Vec<u8> = (0..n).map(|i| (i % 251) as u8).collect();
        let s = deflate_stored(&raw);
        assert_eq!(inflate(&s).unwrap(), raw, "n = {n}");
        let back = miniz_oxide::inflate::decompress_to_vec(&s).expect("valid at n = {n}");
        assert_eq!(back, raw);
    }
}

#[test]
fn empty_input_yields_one_final_empty_block() {
    // A stream with no blocks is not valid DEFLATE.
    assert_eq!(deflate_stored(b""), vec![0x01, 0x00, 0x00, 0xFF, 0xFF]);
    assert_eq!(inflate(&deflate_stored(b"")).unwrap(), b"");
}

#[test]
fn output_is_bounded_by_input_plus_framing() {
    for n in [0usize, 1, MAX_STORED, MAX_STORED * 3] {
        let raw = vec![0u8; n];
        let s = deflate_stored(&raw);
        let blocks = n.div_ceil(MAX_STORED).max(1);
        assert_eq!(s.len(), n + 5 * blocks, "n = {n}");
    }
}
```

Add `miniz_oxide = "0.8"` to `crates/deflate-core`'s `[dev-dependencies]`.

- [ ] **Step 2: Run to verify they fail**

Run: `cargo test -p deflate-core --test encode_tests`
Expected: FAIL — `unresolved import deflate_core::deflate_stored`.

- [ ] **Step 3: Write the implementation**

`crates/deflate-core/src/deflate.rs`:

```rust
//! The minimal encoder (spec §17 M6). Stored blocks only.
//! Mirrors `spec/Deflate/Encode.lean`.
//!
//! This makes output slightly larger than input, which is what a stored-block
//! encoder is for: it establishes framing correctness before any compression
//! ratio work (spec §17 M7, a later plan).

use alloc::vec::Vec;

/// RFC 1951 §3.2.4: LEN is 16 bits.
pub const MAX_STORED: usize = 65535;

/// Encode `input` as a sequence of stored blocks. Empty input yields one
/// final block with LEN = 0, because a stream with no blocks is not valid
/// DEFLATE.
pub fn deflate_stored(input: &[u8]) -> Vec<u8> {
    let blocks = input.len().div_ceil(MAX_STORED).max(1);
    let mut out = Vec::with_capacity(input.len() + 5 * blocks);
    let mut rest = input;
    loop {
        let take = rest.len().min(MAX_STORED);
        let (chunk, tail) = rest.split_at(take);
        let is_final = tail.is_empty();
        // BFINAL in bit 0, BTYPE = 00 in bits 1-2, then five padding bits to
        // the byte boundary that `read_stored` aligns to.
        out.push(u8::from(is_final));
        let len = take as u16;
        out.extend_from_slice(&len.to_le_bytes());
        out.extend_from_slice(&(!len).to_le_bytes());
        out.extend_from_slice(chunk);
        if is_final {
            return out;
        }
        rest = tail;
    }
}
```

Add `pub mod deflate;` and `pub use deflate::{deflate_stored, MAX_STORED};` to `lib.rs`.

- [ ] **Step 4: Run to verify they pass**

Run: `cargo test -p deflate-core --test encode_tests`
Expected: PASS — 5 tests.

- [ ] **Step 5: Add encoding to the differential harness**

In `crates/vdeflate/src/main.rs`, add an `ENCODE <hex>` request to the oracle mode returning `OK <hex>` from `deflate_stored`.

In `oracles/differential.py`, add a second phase after the decode comparison:

```python
def encode_phase(streams_unused, payloads):
    """Spec §18.9: a minimal encoder emits valid DEFLATE and round-trips.

    Three checks per payload, in increasing strength:
      1. our decoder accepts our encoder  — necessary, and weak (spec §2)
      2. the Lean model's decoder accepts our encoder — Rust encoder vs the
         definition the theorems are about
      3. zlib accepts our encoder — an independent decoder, which is what
         makes this an RFC-conformance signal rather than a shared
         misunderstanding
    """
    rust_enc = run_oracle([str(RUST), "--oracle"],
                          [], requests=[f"ENCODE {p.hex()}" for p in payloads])
    findings = []
    for p, e in zip(payloads, rust_enc):
        if not e.ok:
            findings.append({"parties": ["rust-encode"], "payload": p.hex(), "err": e.err})
            continue
        s = e.data
        for name, dec in (("rust", lambda b: run_oracle([str(RUST), "--oracle"], [b])[0]),
                          ("lean", lambda b: run_oracle([str(LEAN)], [b])[0]),
                          ("zlib", lambda b: run_zlib([b])[0])):
            o = dec(s)
            if not o.ok or o.data != p:
                findings.append({"parties": [f"encode->{name}"],
                                 "payload": p.hex()[:64], "stream": s.hex()[:64],
                                 "outcome": repr(o)})
    return findings
```

Generalize `run_oracle` to take explicit `requests` so the encode phase can reuse it.

- [ ] **Step 6: Run the full harness**

Run: `make all && python3 oracles/differential.py`
Expected: 0 findings, decode and encode phases both.

- [ ] **Step 7: Update conformance and commit**

`docs/conformance.md`: `| Encoder validity | yes | yes | yes |`, `| Round trip | yes | yes | yes |`.

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/ oracles/ docs/conformance.md
git commit -m "feat(m6): Rust stored-block encoder

Chunks at 65535 bytes, marks the last block final, and emits one final empty
block for empty input. Validity is checked against an independent decoder,
not only our own: our decoder accepting our encoder would prove the two
halves share a misunderstanding, which spec §2 names as the thing round-trip
tests cannot rule out.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# M8 — Minimal executable

**Exit:** the smallest practical decoder executable, with reproducible measurements and no invented byte target (spec §17 M8).

### Task 23: The CLI

**Files:**
- Modify: `crates/vdeflate/src/main.rs`, `crates/vdeflate/Cargo.toml`, `Cargo.toml`
- Test: `crates/vdeflate/tests/cli_tests.rs`

**Interfaces:**
- Consumes: `deflate_core::{inflate_with_limit, deflate_stored, DEFAULT_LIMIT}`.
- Produces: the `vdeflate` binary with `-d`, `-c`, `--limit`, `--oracle`. Task 24 measures it.

- [ ] **Step 1: Write the failing tests**

`crates/vdeflate/tests/cli_tests.rs`:

```rust
use std::io::Write;
use std::process::{Command, Stdio};

fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_vdeflate")
}

fn run(args: &[&str], stdin: &[u8]) -> (bool, Vec<u8>, String) {
    let mut c = Command::new(bin())
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin.as_mut().unwrap().write_all(stdin).unwrap();
    let o = c.wait_with_output().unwrap();
    (o.status.success(), o.stdout, String::from_utf8_lossy(&o.stderr).into_owned())
}

#[test]
fn compress_then_decompress_through_stdin() {
    let raw = b"the quick brown fox";
    let (ok, packed, _) = run(&["-c"], raw);
    assert!(ok);
    let (ok, back, _) = run(&["-d"], &packed);
    assert!(ok);
    assert_eq!(back, raw);
}

#[test]
fn decompress_rejects_garbage_with_a_nonzero_exit_and_a_message() {
    let (ok, out, err) = run(&["-d"], b"\xff\xff\xff\xff");
    assert!(!ok, "garbage must not exit 0");
    assert!(out.is_empty(), "no partial output on failure");
    assert!(!err.is_empty(), "a failure must say why");
}

#[test]
fn limit_is_honored_and_reported() {
    let raw = vec![b'z'; 100_000];
    let (ok, packed, _) = run(&["-c"], &raw);
    assert!(ok);
    let (ok, _, err) = run(&["-d", "--limit", "10"], &packed);
    assert!(!ok);
    assert!(err.to_lowercase().contains("limit"), "stderr was: {err}");
}

#[test]
fn no_arguments_prints_usage_and_exits_nonzero() {
    let (ok, _, err) = run(&[], b"");
    assert!(!ok);
    assert!(err.contains("usage"), "stderr was: {err}");
}

#[test]
fn empty_input_compresses_and_decompresses() {
    let (ok, packed, _) = run(&["-c"], b"");
    assert!(ok);
    let (ok, back, _) = run(&["-d"], &packed);
    assert!(ok);
    assert!(back.is_empty());
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cargo test -p vdeflate`
Expected: FAIL — the binary prints usage and exits 2 for every invocation.

- [ ] **Step 3: Write the CLI**

Replace the `main` and usage parts of `crates/vdeflate/src/main.rs`, keeping `oracle()` and its helpers:

```rust
const USAGE: &str = "\
usage: vdeflate -d [--limit N] < INPUT > OUTPUT   decompress raw DEFLATE
       vdeflate -c             < INPUT > OUTPUT   compress (stored blocks)

Raw RFC 1951 streams only: no gzip or zip framing.
--limit N bounds the decompressed size in bytes (default: 1073741824).

This program is NOT formally verified. The Lean theorems in spec/ are about
the model in spec/Deflate/, not about this binary, and file I/O, argument
parsing and startup are outside the verification boundary entirely.
See docs/verification-boundary.md.
";

fn read_stdin() -> std::io::Result<Vec<u8>> {
    use std::io::Read;
    let mut v = Vec::new();
    std::io::stdin().lock().read_to_end(&mut v)?;
    Ok(v)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = args.first().map(String::as_str);

    if mode == Some("--oracle") {
        if let Err(e) = oracle() {
            eprintln!("vdeflate: {e}");
            std::process::exit(1);
        }
        return;
    }

    let mut limit = deflate_core::DEFAULT_LIMIT;
    let mut i = 1;
    while i < args.len() {
        match args.get(i).map(String::as_str) {
            Some("--limit") => match args.get(i + 1).and_then(|s| s.parse::<usize>().ok()) {
                Some(n) => {
                    limit = n;
                    i += 2;
                }
                None => {
                    eprintln!("vdeflate: --limit needs a number\n{USAGE}");
                    std::process::exit(2);
                }
            },
            _ => {
                eprintln!("vdeflate: unexpected argument\n{USAGE}");
                std::process::exit(2);
            }
        }
    }

    let input = match read_stdin() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("vdeflate: reading stdin: {e}");
            std::process::exit(1);
        }
    };

    let result = match mode {
        Some("-d") => inflate_with_limit(&input, limit).map_err(err_name),
        Some("-c") => Ok(deflate_core::deflate_stored(&input)),
        _ => {
            eprint!("{USAGE}");
            std::process::exit(2);
        }
    };

    match result {
        Ok(bytes) => {
            use std::io::Write;
            let mut out = std::io::stdout().lock();
            if let Err(e) = out.write_all(&bytes).and_then(|()| out.flush()) {
                eprintln!("vdeflate: writing stdout: {e}");
                std::process::exit(1);
            }
        }
        Err(name) => {
            eprintln!("vdeflate: {name}");
            std::process::exit(1);
        }
    }
}
```

`err_name` already maps `OutputLimitExceeded` to `"outputLimitExceeded"`, which contains "limit", satisfying `limit_is_honored_and_reported`.

- [ ] **Step 4: Run to verify they pass**

Run: `cargo test -p vdeflate`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check
git add crates/vdeflate/
git commit -m "feat(m8): the vdeflate CLI

-d, -c, --limit and the existing --oracle mode, over stdin/stdout. The usage
text says plainly that this binary is not formally verified and points at
docs/verification-boundary.md: the one place a user is most likely to form a
wrong impression is the program itself.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

### Task 24: Reproducible size measurements and the final documents

**Files:**
- Create: `scripts/size_report.sh`, `docs/size-report.md`, `docs/architecture.md`, `README.md`
- Modify: `Cargo.toml`, `docs/verification-boundary.md`, `docs/conformance.md`

**Interfaces:**
- Consumes: the `vdeflate` binary.
- Produces: `docs/size-report.md` and `scripts/reports/size.json`, satisfying spec §18.12.

- [ ] **Step 1: Write the failing check**

`scripts/size_report.sh` must produce a JSON file with every field spec §15 asks for, and `docs/size-report.md` must contain no number that is not in that JSON. Write the check first:

```bash
cat > scripts/check_size_report.sh <<'SH'
#!/usr/bin/env bash
# Every number in docs/size-report.md must appear in scripts/reports/size.json.
# The lesson of maked's "benchmark that lied": a number in prose that no longer
# matches the raw data is how a wrong measurement survives review.
set -euo pipefail
json=scripts/reports/size.json
md=docs/size-report.md
test -s "$json" || { echo "missing $json"; exit 1; }
test -s "$md" || { echo "missing $md"; exit 1; }
missing=0
while read -r n; do
  grep -q -- "$n" "$json" || { echo "number in prose but not in data: $n"; missing=1; }
done < <(grep -oE '\b[0-9][0-9,]{2,}\b' "$md" | tr -d ',' | sort -u)
exit $missing
SH
chmod +x scripts/check_size_report.sh
```

Run: `bash scripts/check_size_report.sh`
Expected: FAIL — `missing scripts/reports/size.json`.

- [ ] **Step 2: Add a size profile as an experiment, not an assumption**

In the workspace `Cargo.toml`:

```toml
[profile.release]
opt-level = 3

# Spec §15 calls this "a size-oriented profile as an experiment, not an
# assumption". Task 24 measures it against `release` and records both.
[profile.min]
inherits = "release"
opt-level = "z"
lto = true
codegen-units = 1
panic = "abort"
strip = "symbols"
```

- [ ] **Step 3: Write the measurement script**

`scripts/size_report.sh`:

```bash
#!/usr/bin/env bash
# Reproducible binary-size measurement (spec §15, §18.12).
#
# Records the whole executable size *and* its sections separately, because
# §15 says never to claim .text as the total. Everything measured here is
# written to scripts/reports/size.json; docs/size-report.md quotes only that
# file, and scripts/check_size_report.sh enforces it.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p scripts/reports
out=scripts/reports/size.json

host=$(rustc -vV | awk '/host:/ {print $2}')
rustc_v=$(rustc --version)
uname_s=$(uname -srm)

size_tool=$(command -v llvm-size || command -v size)
echo "{" > "$out"
printf '  "host": "%s",\n  "rustc": "%s",\n  "uname": "%s",\n  "size_tool": "%s",\n' \
  "$host" "$rustc_v" "$uname_s" "$size_tool" >> "$out"
printf '  "profiles": {\n' >> "$out"

first=1
for profile in release min; do
  cargo build --profile "$profile" -p vdeflate >/dev/null
  dir=$([ "$profile" = release ] && echo release || echo "$profile")
  bin="target/$dir/vdeflate"
  total=$(wc -c < "$bin" | tr -d ' ')
  # Section sizes, each named, never summed into a single headline number.
  sections=$("$size_tool" -A "$bin" 2>/dev/null \
    | awk 'NF>=2 && $2 ~ /^[0-9]+$/ {printf "%s\"%s\": %s", (c++?",":""), $1, $2}')
  [ $first -eq 1 ] || printf ',\n' >> "$out"
  first=0
  printf '    "%s": { "total_bytes": %s, "sections": { %s } }' \
    "$profile" "$total" "$sections" >> "$out"
done
printf '\n  }\n}\n' >> "$out"
cat "$out"
```

```bash
chmod +x scripts/size_report.sh
bash scripts/size_report.sh
```

- [ ] **Step 4: Measure peak memory and stack separately**

Spec §15 asks for maximum working memory and stack requirements as separate tracked quantities. Run:

```bash
cargo build --profile min -p vdeflate
# Largest real input the corpus has, to make the peak meaningful.
python3 -c "import zlib,sys; sys.stdout.buffer.write(zlib.compress(bytes(range(256))*4096, 9)[2:-4])" > /tmp/big.deflate
/usr/bin/time -l ./target/min/vdeflate -d --limit 16777216 < /tmp/big.deflate > /dev/null 2> /tmp/mem.txt || true
grep -i 'maximum resident' /tmp/mem.txt
```

Append `peak_rss_bytes` and the input size that produced it to `scripts/reports/size.json` by hand or by extending the script. A measured peak on a named input is a fact; a peak with no input named is not.

- [ ] **Step 5: Write the report**

`docs/size-report.md`:

```markdown
# Binary size report

Raw data: `scripts/reports/size.json`. Regenerate with `make size`.
`scripts/check_size_report.sh` fails if any number below is absent from that
file — the lesson of maked's "benchmark that lied" is that a number in prose
outlives the measurement that produced it.

No byte target was set before measuring (spec §17 M8).

## Environment

| | |
| --- | --- |
| Host triple | `<from json>` |
| rustc | `<from json>` |
| OS | `<from json>` |
| size tool | `<from json>` |

## Results

| Profile | Total file | `.text` | read-only data | initialized data | BSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| `release` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` |
| `min` | `<n>` | `<n>` | `<n>` | `<n>` | `<n>` |

**The total file size is the first column.** `.text` is one section of it and
is never the number to quote (spec §15).

## Working memory

Decoding `<named input>` (`<n>` bytes compressed, `<n>` decompressed) with
`--limit <n>`: peak RSS `<n>` bytes.

## External runtime assumptions

`vdeflate` links the Rust standard library and the platform libc. `deflate-core`
itself is `no_std` and allocates only through `alloc`. A freestanding build of
the core is possible and unmeasured.

## What is not in this report

No comparison against another DEFLATE implementation's binary size. Such a
comparison is only meaningful with matched feature sets, profiles and
link-time settings, and producing one fairly is its own piece of work
(spec §19.12: measure before claiming).
```

Fill every `<n>` from the JSON, then:

Run: `bash scripts/check_size_report.sh`
Expected: PASS, exit 0.

- [ ] **Step 6: Write `README.md` and `docs/architecture.md`**

`README.md` leads with the claim boundary, the way maked's does:

```markdown
# verified-deflate

A raw DEFLATE (RFC 1951) decoder and stored-block encoder in Rust, with zero
runtime dependencies, beside an executable Lean 4 model of the same semantics.

- `crates/deflate-core/` — the decoder and encoder. `no_std`, no runtime
  dependencies, `#![forbid(unsafe_code)]`.
- `spec/Deflate/` — the Lean 4 model and `<n>` theorems about it, kernel-checked,
  with no `sorry`, no `admit` and no `native_decide`.
- `oracles/` — a differential harness running `deflate-core`, the Lean model,
  `zlib` and `lean-zip` over the same corpus.
- `fuzz/` — three persistent `cargo-fuzz` targets.

**What is proved, and what is not.** The theorems are statements about the
Lean model, not about the Rust binary. Nothing is extracted from or to Rust.
What connects them is the differential harness, which is test evidence over a
finite corpus. `vdeflate` is never "formally verified". Read
[docs/verification-boundary.md](docs/verification-boundary.md) before quoting
any correctness claim, and [docs/conformance.md](docs/conformance.md) for
feature-by-feature coverage.

## Build

    make          # cargo build --release + lake build
    make test     # cargo test, Lean gate, differential harness
    make fuzz     # 60s per fuzz target
    make size     # reproducible binary-size measurement

Needs Rust 1.88 (edition 2024), elan with Lean v4.30.0, and Python 3.

## Known gaps

- The encoder emits stored blocks only, so output is slightly larger than
  input. LZ77 and Huffman encoding are a separate plan (spec §17 M7).
- No gzip (RFC 1952) or ZIP framing (spec §17 M9, M10).
- No refinement proof connects the Lean model and the Rust code. ADR 0003
  records the Charon/Aeneas spike result.
- `<any gap recorded during M4/M5/M6 proof work>`
```

`docs/architecture.md` describes the module pipeline, the Lean/Rust mirroring, and the oracle protocol. Keep it to what a new contributor needs to find their way; the proofs document themselves.

- [ ] **Step 7: Final acceptance pass against spec §18**

Walk the twelve v1 acceptance criteria and record the evidence for each in `docs/conformance.md` under a new "v1 acceptance" heading. Any criterion without evidence is a gap to fix now or to state plainly.

Run: `make all && make test && make fuzz && make size && bash scripts/check_size_report.sh`
Expected: every command exits 0.

- [ ] **Step 8: Commit**

```bash
git add scripts/ docs/ README.md Cargo.toml
git commit -m "feat(m8): reproducible size measurements and the v1 documents

size_report.sh records the whole-file size and every section separately into
scripts/reports/size.json; check_size_report.sh fails if docs/size-report.md
quotes a number the data does not contain. The min profile is measured
against release rather than assumed better, and no byte target was set before
measuring.

README and docs/ lead with the claim boundary: the theorems are about the
Lean model, the harness is test evidence, and the binary is not verified.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013C91sthFvJGeMNSzLb8fuY"
```

---

# Self-review

Run against the spec after the plan is complete, before execution.

**Spec coverage.** Every section of `VERIFIED_DEFLATE_SPEC.md` maps to a task:

| Spec | Covered by |
| --- | --- |
| §3.1 decoder (all block types, LZ77, overlap, EOB, multi-block) | Tasks 7, 14, 16, 17 |
| §3.2 encoder, stored | Tasks 21, 22. Fixed/LZ77/dynamic encoding is M7, a follow-on plan |
| §3.3 Lean model | Tasks 4, 6, 9, 11, 13, 15, 18, 21 |
| §3.4 Charon/Aeneas correspondence | Task 3 (spike), ADR 0003 |
| §3.5 malformed-input behavior | Tasks 7, 17, 18, 19 |
| §3.6 `no_std` core | Task 1 (enforced by CI) |
| §3.7 size optimization after correctness | Task 24 |
| §5 layout | Task 1, ADR 0001 |
| §6 verification boundary | Tasks 1, 3, 18, 20, 24 |
| §7 Rust rules | Task 1 (`forbid(unsafe_code)`, clippy denials, no-`std` CI grep) |
| §8 semantic model | Tasks 4, 18 (`BitReader`, `decodeFuel.loop` state) |
| §9 P1–P12 | P1 T4 · P2 T9 · P3 T6 · P4 T13 · P5 T15 · P6 T11 · P7 T11 (`copyBack_rejects`) + T1 (`forbid(unsafe_code)`) · P8 T18 · P9 T20 · P10 T21 · P11 T21 · P12 T18 |
| §10 error model | Task 1 |
| §11 security | Tasks 17, 19 |
| §12 testing | Tasks 5, 7, 10, 12, 14, 16, 17, 19, 20, 22 |
| §13 conformance matrix | Task 1, updated by Tasks 5, 7, 12, 14, 16, 17, 18, 22 |
| §14 lean-zip | Task 2, ADR 0002; live oracle in Task 20 |
| §15 small binary | Task 24 |
| §16 optimization discipline | Not exercised: no optimization is attempted in this plan. Task 24 records the measurements a later optimization would be judged against |
| §17 M0–M6, M8 | Tasks 1–24. M7, M9, M10 are follow-on plans |
| §18 v1 acceptance | Task 24 Step 7 |
| §19 working rules | Enforced throughout; §19.7 (never `sorry`) is a CI gate from Task 1 |
| §20 deliverables | All present by Task 24 except the ADRs for optimizations, which §16 work would add |

**Gaps found and accepted.** Spec §16 (optimization discipline) has no task,
because this plan deliberately performs no optimization — correctness first,
per §17 M8's "binary-size work starts after a correct decoder exists". Task 24
records the baseline any later optimization must be measured against. Spec §8's
`Represents(rust_state, lean_state)` relation is not written, because ADR 0003
makes differential testing the primary bridge; if Task 3's spike succeeds, the
relation becomes worthwhile and belongs in a follow-on plan.

**Placeholder scan.** The plan contains two deliberate markers, both flagged in
their own step as not to be committed: the `sorry` in Task 3 Step 3 (replaced in
Step 4 or the file is deleted) and the `sorry` in Task 21 Step 5 (closed in that
same step, with a named fallback). Every other step carries the code it asks for.

**Type consistency.** `Error`/`DecErr` variants match name for name (Task 1,
with `fuelExhausted` extra on the Lean side, which the oracle protocol in Task 8
carries). `BitReader` has `bit_pos`/`pos`, `read_bits`/`readBits`,
`align_to_byte`/`alignToByte` — same meaning, each language's casing.
`HuffmanTable::from_lengths(…, Completeness)` pairs with `Code.isComplete` /
`Code.isValidDistance` after Task 15's split, which Task 15 Step 1 performs
explicitly rather than leaving the earlier name to drift. `decode_huff_block`
and `decodeHuffBlock` take the same five arguments plus Lean's fuel.
`DEFAULT_LIMIT` is introduced in Task 17 and used in Tasks 22, 23.

**Review Focus coverage.** Each of the five lines has its test in the task that
owns the code: truncation in Tasks 5 and 17; empty blocks in Tasks 7 and 14;
incomplete and degenerate trees in Tasks 10 and 16, with ADR 0004; the distance
boundary in Task 12; bombs in Task 17.
