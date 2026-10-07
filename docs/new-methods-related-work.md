# Prior work and novelty boundary for the new prototypes

Snapshot date: 2026-10-07. This is an initial primary-source survey, not an
exhaustive originality or patent assessment. Pin implementations in G0 before
code/measurement comparison; master/dev URLs below identify mechanisms only.

| Proposed component | Relevant existing work | What this investigation must establish |
| --- | --- | --- |
| Hash-chain dictionaries, bounded candidate search | [libdeflate hash-chain matcher](https://github.com/ebiggers/libdeflate/blob/master/lib/hc_matchfinder.h), [libdeflate compressor](https://github.com/ebiggers/libdeflate/blob/master/lib/deflate_compress.c) | Exact differences in tag/owner layout, probe order, batching and checked lazy integration; measured value rather than naming an established idea an invention. |
| Grouped comparisons and CPU optimization | [zlib-ng](https://github.com/zlib-ng/zlib-ng) | Portable safe implementation and charged loads/writes; no assumed SIMD benefit. |
| Format-aware reversible transforms and separated streams | [OpenZL](https://github.com/facebook/openzl), [Meta introduction](https://engineering.fb.com/2025/10/06/developer-tools/openzl-open-source-format-aware-compression-framework/) | Byte-exact lexical domain, simple fixed frame, bounded decoder and explicit proof boundary; measure against an appropriate format-aware control when available. |
| Adaptive speed/size, dictionaries | [Zstandard](https://github.com/facebook/zstd), [LZ4](https://github.com/lz4/lz4) | Charge metadata/training/state and compare direct library calls with matched threading and dictionary availability. |
| Context modelling and strong compression | [Brotli](https://github.com/google/brotli), [7z/LZMA2](https://www.7-zip.org/7z.html) | Compare fixed levels, whole-frame bytes, decode cost and RSS, not borrowed headline figures. |
| Interoperable DEFLATE constraints | [RFC 1951](https://datatracker.ietf.org/doc/html/rfc1951), [ZIP specification](https://pkware.cachefly.net/webdocs/APPNOTE/APPNOTE-6.3.8.TXT) | Retain distance/length and framing constraints for A; label B as a separate format requiring its decoder. |

OpenZL explicitly builds specialized compressors from data descriptions with
a common decompressor. Therefore "split structured data into streams" is
already represented in prior work. Cached match prefixes, integer deltas and
dictionary substitution likewise do not by themselves establish novelty.

Our engineering hypotheses are particular implementations of A's owner-checked
prefix filter/group traversal and B's checked byte-exact lexical transform with
a compact, bounded experimental frame. Improvements in correctness scope,
footprint or a measured frontier may be useful without a new compression
principle. Record unsuccessful hypotheses and any close prior mechanism found
during source review. Claims of research novelty need a fuller dedicated search;
they are not a completion requirement of this bounded goal.

## Pinned implementation review at G0 lock

The locally archived libdeflate v1.26 `lib/hc_matchfinder.h` explicitly separates
length-three lookup from its length-four hash chains. Its search first checks
the starting word and, after finding a match, checks the ending and starting
words before extension (`hc_matchfinder_longest_match`, approximately lines
244–311 in the pinned release). Consequently, cheap prefix/end rejection and
separate three/four-byte indexes are established mechanisms, not novelty of A.
Our proposed cached tag still needs an owner check and the guarded fourth-byte
rule to preserve this project's scalar candidate/probe semantics.

The archived zlib-ng 2.3.3 `functable.c` dispatches to architecture-specific
matching/comparison implementations. Its ARM `arch/arm/compare256_neon.c`
compares 16 bytes per vector and locates the first differing byte before
returning a length. This supports investigating compiler/load/traversal costs;
it does not establish that portable grouped candidate loads will be faster.
These are source observations, not benchmark results.

OpenZL's two-attempt setup resolved negatively for a qualified production
control/oracle on this host. The library build succeeded, but the final
production shared-library + upstream CLI setup failed at ARM64 linking. Its
unmeasured structured/trained graphs remain prior work and an explicit limit
on any subsequent superiority statement; the setup failure does not establish
anything about their compression quality or speed.
