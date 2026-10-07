# Experimental DSC1 prototype

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
Both codec settings and model/proof gates remain subject to the fixed research
protocol; the convenience settings are not a measured winning preset.
