# Verified DEFLATE --- Lean 4 + Rust

## Agent Implementation Specification

**Status:** Initial specification\
**Primary language:** Rust\
**Formal verification:** Lean 4\
**Wire format:** RFC 1951 DEFLATE\
**Preferred verification bridge:** Charon + Aeneas

## 1. Mission

Build a small, deterministic DEFLATE compressor/decompressor in Rust
with a machine-checked Lean 4 specification. The project must establish
a traceable relationship between the RFC 1951 semantics, the Lean
reference model, and the actual Rust algorithmic core.

Prefer reusing or adapting `lean-zip` as the formal reference if its
license, definitions, and semantics are suitable. Do not treat unrelated
Lean proofs as verification of the Rust implementation.

The desired chain is:

``` text
RFC 1951
   ↓
Lean 4 reference semantics
   ↕ refinement/correspondence proof
Rust algorithmic core
   ↓
rustc/linker
small executable/library
```

The Lean runtime and proof artifacts do not ship in the final
executable.

## 2. Correctness Target

The following property is required but is NOT sufficient:

``` text
decode(encode(x)) == x
```

Two mutually compatible implementations can round-trip data while both
violating RFC 1951.

The stronger target is:

``` text
RustDecode(stream) = LeanDecode(stream)
RustEncode(input) conforms to RFC 1951
Decode(Encode(input)) = input
```

for the formally supported domain.

Every claim must clearly distinguish: - RFC conformance; - Lean-model
correctness; - Rust/Lean correspondence; - memory safety; -
whole-executable assumptions.

## 3. Goals

1.  Implement a conforming Rust DEFLATE decoder supporting:

    -   stored blocks;
    -   fixed Huffman blocks;
    -   dynamic Huffman blocks;
    -   LZ77 length/distance references;
    -   overlapping back-references;
    -   end-of-block handling;
    -   multiple blocks.

2.  Implement a Rust encoder in stages:

    -   stored blocks;
    -   fixed Huffman;
    -   basic LZ77;
    -   dynamic Huffman;
    -   later compression-ratio improvements.

3.  Maintain a Lean 4 semantic model of the proof-critical behavior.

4.  Establish correspondence between the Rust core and Lean model,
    preferably using: `Rust → Charon → LLBC → Aeneas → Lean 4`.

5.  Define safe deterministic behavior for malformed/truncated input.

6.  Keep the core suitable for `no_std` where practical.

7.  After correctness, optimize a minimal standalone decoder for
    executable size.

## 4. Non-goals for v1

Do not initially implement: - ZIP containers; - gzip containers; -
encryption; - filesystem/archive metadata; - network streaming; -
parallel compression; - SIMD; - architecture-specific unsafe
optimization; - maximum compression ratio.

gzip and ZIP are later wrappers around the DEFLATE core.

## 5. Recommended Repository Layout

``` text
verified-deflate/
├── README.md
├── Cargo.toml
├── lakefile.toml
├── lean-toolchain
├── spec/
│   └── Deflate/
│       ├── Bitstream.lean
│       ├── Huffman.lean
│       ├── LZ77.lean
│       ├── Block.lean
│       ├── Decode.lean
│       ├── Encode.lean
│       └── Properties.lean
├── crates/
│   ├── deflate-core/src/
│   │   ├── lib.rs
│   │   ├── bitstream.rs
│   │   ├── huffman.rs
│   │   ├── lz77.rs
│   │   ├── block.rs
│   │   ├── inflate.rs
│   │   ├── deflate.rs
│   │   └── error.rs
│   └── vdeflate/src/main.rs
├── verification/
│   ├── aeneas/
│   ├── generated/
│   ├── proofs/
│   └── README.md
├── tests/
│   ├── vectors/
│   ├── differential/
│   ├── malformed/
│   └── roundtrip/
├── fuzz/
├── scripts/
└── docs/
    ├── architecture.md
    ├── verification-boundary.md
    ├── conformance.md
    └── size-report.md
```

The exact layout may change for tooling reasons, but keep specification,
verified core, generated verification artifacts, platform/CLI code, and
tests explicitly separated.

## 6. Verification Boundary

### Verified core

Aim to verify: - bit-level input interpretation; - bit position
advancement; - Huffman construction semantics; - Huffman symbol
decoding; - length-code decoding; - distance-code decoding; - LZ77 copy
semantics; - block-state transitions; - output construction; - encoder
block generation; - modeled error behavior.

### Initially outside the proof boundary

May initially remain unverified: - OS file I/O; - CLI parsing; -
executable startup; - allocator/runtime implementation; - linker; -
compiler correctness; - terminal handling; - benchmarking
infrastructure.

Never call the complete executable "formally verified" when only the
algorithmic core is proved.

## 7. Rust Rules

Design for proofability before micro-optimization.

Prefer: - safe Rust; - explicit state machines; - simple
structs/enums; - slices and bounded indexes; - deterministic
functions; - explicit errors; - small functions; - clear integer
bounds; - minimal generic/trait abstraction in the verified core.

Avoid in the verified core unless proven compatible with the
toolchain: - `unsafe`; - async; - threads; - FFI; - interior
mutability; - complex trait machinery; - architecture intrinsics; -
hidden global state.

Test Charon/Aeneas translation early. Do not implement the entire
decoder and only then discover that the architecture cannot be
translated.

Recommended development loop:

``` text
small Rust function
→ translate with Charon/Aeneas
→ prove/refine in Lean
→ add one semantic feature
→ translate again
→ prove again
```

## 8. Semantic Model

Define an explicit abstract machine state containing at least: - input
bit position; - produced output; - current block information; -
final-block state; - decoder state.

Define a representation relation such as:

``` text
Represents(rust_state, lean_state)
```

The desired step/refinement theorem is conceptually:

``` text
Represents(rs, ls)
∧ RustStep(rs) = rs'
∧ LeanStep(ls) = ls'
→ Represents(rs', ls')
```

A whole-function refinement theorem is also acceptable if easier to
maintain.

## 9. Mandatory Proof Obligations

### P1 --- Bit reader

Show that reading N bits consumes the intended bits, advances correctly,
leaves unrelated input unchanged, and reports insufficient input
deterministically.

### P2 --- Huffman decoding

For valid canonical descriptions, show that decoding returns the
represented symbol and consumes the correct number of bits. Invalid
descriptions must have defined rejection behavior.

### P3 --- Stored blocks

Verify byte alignment, `LEN`, `NLEN`, payload copying, and rejection of
an invalid length complement.

### P4 --- Fixed Huffman

Verify the fixed literal/length and distance code semantics defined by
RFC 1951.

### P5 --- Dynamic Huffman

Cover `HLIT`, `HDIST`, `HCLEN`, code-length alphabet ordering, repeat
symbols 16/17/18, literal/length tree construction, and distance tree
construction.

### P6 --- LZ77 copies

For every accepted length/distance pair, prove that the source is valid
and the produced bytes match DEFLATE semantics. Correctly handle
overlapping back-references.

### P7 --- Memory safety

Every input/output access must remain in range. Malformed input must not
create an invalid access.

### P8 --- Progress/termination

The decoder must not loop forever without consuming input, producing
output, terminating, or returning an error. Establish termination for
finite valid streams under the model.

### P9 --- Decoder correspondence

Establish an explicit theorem equivalent to:

``` text
RustDecode(stream) = LeanDecode(stream)
```

for the supported valid-stream domain.

### P10 --- Encoder validity

Every successful Rust encoding must be a valid RFC 1951 stream.

### P11 --- Round trip

Establish:

``` text
Decode(Encode(input)) = input
```

for supported inputs.

### P12 --- Deterministic malformed-input behavior

Invalid inputs must have documented deterministic failure semantics.

## 10. Error Model

Use explicit errors rather than panics for malformed input. A starting
shape:

``` rust
pub enum Error {
    UnexpectedEof,
    InvalidBlockType,
    InvalidStoredLength,
    InvalidHuffmanTree,
    InvalidCode,
    InvalidDistance,
    InvalidLength,
    OutputLimitExceeded,
}
```

Change the exact enum as required by the implementation.

## 11. Security Requirements

Treat compressed input as hostile.

Required: - no unsafe memory access; - no memory-safety-relevant integer
overflow; - impossible distances rejected; - malformed Huffman
descriptions rejected; - deterministic truncated-input handling; -
configurable output limit for untrusted input; - fuzzing of all parser
layers.

A tiny compressed stream may expand enormously. The public decoder API
must allow callers to bound decompressed output.

## 12. Testing

Formal proof does not replace interoperability testing.

Implement: - unit tests for bit I/O, Huffman logic, length/distance
mappings, block types, and overlapping copies; - known vectors for
empty, one-byte, repeated, random, compressible, incompressible,
multi-block, and boundary cases; - differential decoding against mature
independent DEFLATE implementations; - cross tests:
`our encode → reference decode` and `reference encode → our decode`; -
property tests including `decode(encode(x)) == x`; - fuzzing of the full
decoder, dynamic-tree parser, Huffman parser, LZ77 logic, truncations,
and bit mutations.

Every crash or hang on malformed input is a bug.

## 13. Conformance Matrix

Maintain `docs/conformance.md`:

``` text
Feature                       Implemented  Tested  Formally covered
Stored blocks                 yes/no       yes/no  yes/no
Fixed Huffman                 yes/no       yes/no  yes/no
Dynamic Huffman               yes/no       yes/no  yes/no
Multi-block streams           yes/no       yes/no  yes/no
Overlapping back-reference    yes/no       yes/no  yes/no
Malformed input rejection     yes/no       yes/no  yes/no
Encoder validity              yes/no       yes/no  yes/no
```

Do not mark a feature formally covered because a different
implementation happens to have a proof.

## 14. `lean-zip` Integration

Before committing to architecture:

1.  inspect `lean-zip`;
2.  record its license and exact revision;
3.  map its definitions/theorems to RFC 1951 features;
4.  determine whether to depend on it, adapt it, reuse definitions, or
    only compare semantics;
5.  document semantic differences and assumptions.

If direct reuse is unsuitable, create a smaller project-specific Lean
model while preserving `lean-zip` as a reference.

## 15. Small Binary Track

Binary-size work starts after a correct decoder exists.

Provide a minimal executable, conceptually:

``` text
vdeflate INPUT > OUTPUT
```

Use a size-oriented profile as an experiment, not an assumption:

``` toml
[profile.release]
opt-level = "z"
lto = true
codegen-units = 1
panic = "abort"
strip = "symbols"
```

Measure alternatives.

Track separately: - complete executable size; - `.text`; - read-only
data; - initialized data; - BSS; - maximum working memory; - stack
requirements; - external runtime assumptions.

Never claim `.text` size as total executable size.

## 16. Optimization Discipline

Optimizations may include: - smaller integer representations; - packed
flags; - specialized fixed-Huffman paths; - table simplification; -
abstraction removal; - smaller error representations; - proven
equivalent specialized algorithms.

For every significant optimization:

``` text
baseline
→ optimized candidate
→ proof/refinement check
→ test suite
→ size/performance measurement
```

Do not use Lean as decoration. An optimization affecting verified
semantics must either remain inside the established refinement proof or
generate a new proof obligation.

## 17. Milestones

### M0 --- Toolchain/research spike

Deliver RFC notes, `lean-zip` assessment, Charon/Aeneas compatibility
notes, and one tiny Rust→Lean proof.

**Exit:** one Rust state transition is translated and proved against a
Lean specification.

### M1 --- Bitstream

Implement and verify LSB-first reads, alignment, bounds, and EOF
semantics.

### M2 --- Stored blocks

Implement/verify stored blocks and `LEN/NLEN`.

### M3 --- Fixed Huffman decoder

Implement canonical fixed decoding, literals, end-of-block, and
length/distance references.

### M4 --- Dynamic Huffman decoder

Implement/verify dynamic code descriptions and tables.

### M5 --- Complete decoder

Support all block types and combinations. Run differential tests,
fuzzing, malformed corpus, and correspondence proofs.

### M6 --- Minimal encoder

A stored-block-only encoder is acceptable first. It must produce valid
DEFLATE.

### M7 --- Compressed encoder

Add LZ77, fixed Huffman, then optional dynamic Huffman. Correctness
before ratio.

### M8 --- Minimal executable

Produce the smallest practical verified-core decoder executable and
document measurements. Do not invent a byte target before measuring real
builds.

### M9 --- gzip

Add RFC 1952 framing as a separate layer.

### M10 --- ZIP

Add minimal ZIP extraction/creation around the verified DEFLATE core.
ZIP verification is separate scope.

## 18. v1 Acceptance Criteria

v1 is complete when:

1.  Rust decodes stored, fixed, and dynamic DEFLATE blocks.
2.  Multi-block streams work.
3.  Malformed/truncated streams return explicit errors rather than
    panicking.
4.  The core contains no unjustified `unsafe`.
5.  Differential tests against independent implementations pass.
6.  A persistent fuzz target exists and has no known reproducible
    crash/hang.
7.  Lean proofs cover the documented v1 verification boundary.
8.  Rust/Lean correspondence is demonstrated for the proof-critical
    core, not merely asserted.
9.  A minimal encoder emits valid DEFLATE and round-trips supported
    input.
10. `docs/verification-boundary.md` states exactly what is and is not
    formally verified.
11. `docs/conformance.md` accurately reports implementation/test/proof
    coverage.
12. `docs/size-report.md` reports reproducible binary-size measurements.

## 19. Agent Working Rules

The implementation agent must:

1.  begin with M0, not with a full rewrite;
2.  inspect current upstream versions of Lean 4, Charon, Aeneas, and
    `lean-zip`;
3.  pin toolchain/revisions used for reproducibility;
4.  make small commits by semantic feature;
5.  keep the build green;
6.  run Rust tests and Lean checks after proof-relevant changes;
7.  never replace a failed proof with `sorry`, an axiom, or an
    undocumented assumption merely to pass CI;
8.  record unavoidable assumptions explicitly;
9.  avoid `unsafe` in the verified core unless separately justified and
    formally accounted for;
10. keep generated verification code separate from handwritten proofs;
11. preserve failing/minimized fuzz cases as regression tests;
12. measure before making performance or size claims;
13. prefer a smaller verified semantic core over a large architecture
    that the proof toolchain cannot handle.

## 20. Deliverables

The repository must eventually contain:

-   Rust DEFLATE core;
-   Lean 4 specification;
-   Rust→Lean verification artifacts;
-   handwritten proofs;
-   conformance matrix;
-   verification-boundary document;
-   test vectors;
-   differential tests;
-   fuzz targets and regression corpus;
-   minimal CLI;
-   reproducible build instructions;
-   binary-size report;
-   architecture decision records for major deviations.

## 21. Future Direction

After v1:

``` text
verified DEFLATE
    ↓
verified/minimal gzip
    ↓
ZIP container
    ↓
broader archive library
    ↓
additional codecs such as LZ4 or Zstandard
```

A separate research track may investigate the smallest executable
DEFLATE decoder whose algorithmic core is formally verified in Lean 4.

The long-term methodology is:

``` text
specify
→ implement
→ establish correspondence
→ prove properties
→ test interoperability
→ fuzz hostile inputs
→ optimize
→ measure
```

Correctness claims must remain stronger than round-trip tests and
narrower than the evidence actually supports.
