# Experimental DSC1 prototype (rejected research family)

Status: research closed on 2026-10-07. All 12 preregistered configurations
failed the one-session training screen; no sentinel or production release was
selected. The best-size setting produces 8.52% more bytes and encodes 38.58×
slower than zstd-3 on the eight structured training groups. These are training
point estimates, not independent final-test results. See the
[closure report](../../docs/new-methods-report.md) and
[maintenance handover](../../docs/handover.md).

Byte-exact lexical transforms over arbitrary input bytes, independent chunks,
literal/dictionary/numeric streams and baseline DEFLATE compression. This is a
research crate, unpublished and outside the existing DEFLATE model boundary.
It has no production-performance or formal-verification claim.

See [wire specification](../../docs/structured-codec-spec.md),
[investigation plan](../../docs/new-methods-plan.md) and
[fixed protocol](../../scripts/new_methods_protocol.json).
The library uses `no_std + alloc`, forbids unsafe code and depends only on local
`deflate-core`. The optional `cli` feature builds a research file tool.

```sh
cargo build --release -p structured-codec --features cli
target/release/structured-tool encode input.json output.dsc1 16 keys checked-delta
target/release/structured-tool decode output.dsc1 recovered.json 67108864
python3 scripts/structured_reference.py decode output.dsc1 independent.json
```

Inputs need not be JSON or UTF-8. The encoder reconstructs every proposed
transform, compares its bytes and includes all scans, discarded alternatives,
metadata and CRC in its work. Each chunk chooses the smallest raw, DEFLATE or
transformed payload; this gives no guarantee relative to other codecs. Tiny
files still pay frame overhead. Decoders reject suffixes and noncanonical
varints, check stream/output bounds and validate chunk/frame CRCs.

The 64 MiB convenience output ceiling is a caller policy, not a format size
limit. Pass an explicit ceiling through `decode_with_limit` for other policies.
The former protocol and uncompleted model/proof gates are retained as historical
requirements. Full transform/frame model proofs were not completed; the
convenience settings are not a measured winning preset. Commands above reproduce
the retained prototype and do not initiate a new research campaign.
