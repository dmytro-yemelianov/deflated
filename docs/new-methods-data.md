# Fresh data and preserved regressions

G1's acquisition recipes are fixed in
[`new_methods_sources.json`](../scripts/new_methods_sources.json).
There are 36 fresh source groups: twelve per split, with four shared between
tracks A and B within the same split. Each track has eight groups per split.
A covers source code, prose, JSON, line records, fonts and compressed archives.
B covers JSON and line records in every split, with additional NDJSON in
training and validation. Held B uses seven JSON groups and one CSV group.
This is a finite fixture population; eight repository groups do not establish
independence of every schema or a universal structured-data result.

Files were selected using repository tree paths, extensions, sizes and license
metadata, before downloading their bodies or encoding any study input.
Every GitHub file and license snapshot is checked against the blob identity
in its pinned commit tree. Compressed archives use pinned-commit codeload URLs
and content-locked download hashes. Files up to 1 MiB remain complete; larger
files use the recorded first 1 MiB. Druid's gzip source is decompressed with
a 64 MiB limit before this slice. No slice is advertised as complete JSON.
Source bodies remain in ignored `target/`; published receipts contain recipes,
hashes, extraction ranges, provenance and license metadata.

Licensing metadata distinguishes code grants from dataset terms. SPDX has no
repository-wide license assertion in the acquired README; Vega and OWID retain
their dataset-specific/third-party qualifications. Druid's tutorial is derived
from Wikipedia data. FlightHelmet's model attribution explicitly identifies
CC0; the earlier BrainStem candidate was excluded because its model had separate
Poser terms. A repository license is not represented as overriding third-party
data terms. No real corpus bytes are redistributed in this repository.

The candidate selection excluded Loki/Prometheus copies of `20kseries.json`,
NativeJSON/Jackson copies of CITM, package-lock templates outside training,
and notebook templates outside the held nbformat group. TensorRT validation
uses its performance schema, not a notebook. Declared project lineages cannot
occur in multiple splits. The 24 project lineages from the previous encoder
study are excluded, and the Canterbury/large/Silesia inputs and every recorded
older search corpus are retained in a separate regression index.

Deduplication checks exact hashes, contained byte copies of at least 4 KiB,
and at least 80% shared content-defined chunk weight. Gear boundaries have
256/4096-byte bounds and average about 1 KiB, so shifted copies do not depend
on a shared file alignment. Hashes are used only for integrity/deduplication;
none is exposed as an optimizer feature. This check detects byte reuse,
not every semantic relationship or common generator. The published supplemental
audit checks fresh nonshared hashes against all eighteen historical corpus
manifests and compares fresh real bodies against the unique historical real
inputs. Old historical data and manifests are read without modification.

The deterministic generator adds twelve families, two regimes per split:
13/14 training, 15/16 validation and 17/18 held. These produce 72 cases of
256 KiB for production-hash collisions, equal trigrams with unequal fourth
bytes, bucket eviction, ring owners, lazy lookahead, cost thresholds, numeric
spellings/overflow, escaped/raw invalid UTF-8, schema drift, unique keys and
chunk-spanning lexemes. Construction checks verify actual multiply-hash
collisions. Lazy/ring workloads exercise these situations; exact state and
near-u32-limit witnesses still belong to matcher correctness tests.

Six additional 8 MiB cases exercise long history and structured chunk cuts,
one of each per split. They have separate scores and never enter primary
aggregates. Twelve shared tiny and nine shared boundary witnesses are explicitly
labelled correctness/stress, without independent holdout claims. Complete
synthetic regeneration checks all 99 hashes; old regimes 7--12 remain regression.
Held acquisition and generation have involved no encoding, selector features,
teacher labels, dictionary fitting or schema fitting.

Reproduce into fresh output directories; sealed outputs refuse replacement:

```sh
python3 scripts/test_new_methods_corpus.py
python3 scripts/test_new_methods_synthetic.py
python3 scripts/new_methods_corpus.py --out target/reproduce/new-methods-corpus
python3 scripts/new_methods_synthetic.py --out target/reproduce/new-methods-synthetic
python3 scripts/test_new_methods_data_artifacts.py
```

`new_methods_corpus.py --check` audits the locally acquired bodies, licenses,
old primary corpus and deduplication. The published-receipt test regenerates
synthetics in isolation and runs in CI without downloading real data. Supplemental
`new_methods_regressions.py` needs the eighteen historical local corpus roots;
its immutable index preserves all their input hashes and original paths.
Partial acquisition failures retain their own receipt; cached successes can
resume only under the same inventory/tool intent. Screening and performance
claims remain separate G2/G3 work.
