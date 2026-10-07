#!/usr/bin/env python3
"""Export P0/P1 evidence and time-weighted encoder sample attribution."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import statistics

from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, validate, write_json
from encoder_measure import sha


def analyze(profiles, rows):
    result = {}
    for method in profiles["protocol"]["methods"]:
        functions, groups, total = collections.Counter(), collections.Counter(), 0.0
        for profile in profiles["rows"]:
            if profile["method"] != method or profile["case"]["scope"] != "new-real-train":
                continue
            found = [r for r in rows if r["method"] == method and r["input"] == profile["case"]["raw_path"]]
            median = statistics.median(r["encode_ns"] for r in found)
            total += median
            for label, count in profile["nearest_encoder_caller_samples"].items():
                weighted = median * count / profile["samples"]
                functions[label] += weighted
                group = label.split("/", 1)[1].split("::", 1)[0] if "/" in label else label
                groups[group] += weighted
        result[method] = {"unprofiled_encode_median_ns_sum": total,
             "nearest_encoder_caller_weighted_pct": {k: 100 * v / total for k, v in functions.most_common()},
             "source_group_weighted_pct": {k: 100 * v / total for k, v in groups.most_common()}}
    return result


def run(profile_dir, baseline_dir, out):
    profiles = json.loads((profile_dir / "result.json").read_text())
    baseline = json.loads((baseline_dir / "result.json").read_text())
    raw = (baseline_dir / "measurements.jsonl").read_bytes()
    if sha(baseline_dir / "measurements.jsonl") != baseline["raw_ledger_sha256"]:
        raise ValueError("baseline ledger changed")
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != baseline["rows"] or len({(r["session"], r["method"], r["input"]) for r in rows}) != len(rows):
        raise ValueError("missing/duplicate paired observations")
    protocol = profiles["protocol"]
    expected = {(c["raw_path"], m) for c in protocol["cases"] for m in protocol["methods"]}
    actual = {(p["case"]["raw_path"], p["method"]) for p in profiles["rows"]}
    if actual != expected or len(profiles["rows"]) != len(expected):
        raise ValueError("profile coverage changed")
    for profile in profiles["rows"]:
        path = ROOT / profile["profile_path"]
        if sha(path) != profile["profile_sha256"]:
            raise ValueError("raw sampling profile changed")
        n = profile["samples"]
        if sum(profile["exclusive_samples"].values()) != n or sum(profile["nearest_encoder_caller_samples"].values()) != n:
            raise ValueError("exclusive/context sample accounting differs")
        matching = [r for r in rows if r["input"] == profile["case"]["raw_path"] and r["method"] == profile["method"]]
        if not matching or {r["packed_sha256"] for r in matching} != {profile["packet_sha256"]}:
            raise ValueError("profile packets differ from measured baseline")
    corpus = json.loads((CORPUS_OUT / "manifest.json").read_text())
    coverage = validate(CORPUS_OUT, corpus)
    if sha(CORPUS_OUT / "manifest.json") != protocol["corpus_manifest_sha256"]:
        raise ValueError("corpus changed")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "encoder-corpus.json", corpus)
    write_json(out / "encoder-baseline-train.json", baseline)
    (out / "encoder-baseline-train-measurements.jsonl.gz").write_bytes(gzip.compress(raw, mtime=0))
    profiles["time_weighted_attribution"] = analyze(profiles, rows)
    profiles["analysis_source_sha256"] = sha(Path(__file__))
    profiles["baseline_report_sha256"] = sha(out / "encoder-baseline-train.json")
    write_json(out / "encoder-profile.json", profiles)
    lines = ["# P0/P1: refreshed Rust encoder profiles", "",
        "Status: real-corpus contract, original controls and initial profiling complete;",
        "new synthetic regimes and implementation experiments remain pending.", "",
        "The original S9 worker is sealed at commit `14f15e63e1a8955c5cfebf869ce065f29dd950fc`,",
        "including its exact binary, source archive, compiler/flags and both policy payloads.",
        "The new corpus has 24 declared independent source groups, eight per split,",
        "covering six content classes in every split. Hashes and aligned-chunk checks",
        "reject copies; publisher URLs, pinned Git commits where applicable, license",
        "snapshots and extraction ranges are recorded. Each input is a complete file",
        "up to 1 MiB or its recorded first 1 MiB. The eight new final-test inputs have",
        "not been encoded or used for selector features.", "",
        "The warm pilot has five paired sessions, 11 original methods and 11 inputs:",
        "eight new training sources and three known S9 outliers (605 rows). Encoder",
        "allocations/selection/emission are timed; I/O and three-decoder validation",
        "are excluded. It is training evidence, not final-test promotion evidence.", "",
        "| Original method | Warm speed vs paired Balanced | Packed-size change | Worst file growth |",
        "| --- | ---: | ---: | ---: |"]
    for name, metric in baseline["metrics"]["new-real-train"].items():
        lines.append(f"| {name} | {metric['warm_speed_vs_paired_balanced']:.3f}× | {metric['packed_size_change_pct']:+.3f}% | {100*(metric['worst_file_size_ratio']-1):+.2f}% |")
    lines += ["", "## Sampling and attribution", "",
        "Apple M5, rustc 1.88.0, release O3 with line tables. Four methods × 11 inputs",
        "give 44 two-second profiles. The profiling worker contains an encoder-only",
        "loop; its packets match the sealed original worker and warm ledger. The",
        "sampler does not run any decoder. Raw traces remain under",
        "`target/encoder-performance/profile-train-v1/` with hashes in the report.", "",
        "`atos -i` resolves 1648 unique binary addresses. Inclusive accounting takes",
        "the union of inline frames and sampled ancestors; these percentages overlap.",
        "Exclusive accounting records the innermost frame. A separate additive",
        "nearest-encoder-caller view attributes inlined standard-library operations",
        "and library calls to their closest core/reference caller. A generic type",
        "argument containing `deflate_core` does not make a standard-library function",
        "a core function. Anonymous closure names can still combine multiple sites.", "",
        "The following shares use that caller view, weighted by the pilot's unprofiled",
        "per-file median encode times, rather than giving every two-second trace equal",
        "weight. These are sampled cost estimates, not confidence intervals.", "",
        "| Method | Matcher | Bit writer | Dynamic emission/frequencies | Huffman construction |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for name in ("balanced", "best", "bayesian-compromise"):
        groups = profiles["time_weighted_attribution"][name]["source_group_weighted_pct"]
        matcher = groups.get("matcher.rs", 0) + groups.get("matcher_flat.rs", 0)
        lines.append(f"| {name} | {matcher:.2f}% | {groups.get('bitwriter.rs',0):.2f}% | {groups.get('encode_dynamic.rs',0):.2f}% | {groups.get('huffman_build.rs',0):.2f}% |")
    lines += ["", "The dominant cost is matching, with code writing a useful secondary target.",
        "Best spends more time in search and frequency/Huffman work. The miniz6",
        "reference spends about 45% in `find_match`, 33% in `compress_normal` and",
        "15% in `read_u16_le` under the same weighted attribution. Its token-search",
        "choices differ; sample shares alone do not explain an absolute speed ratio.", "",
        "## Selected P2 implementation spikes", "",
        "1. Replace the per-bit loop in `BitWriter::write_code` with bounded bit",
        "   reversal. Preserve every width, clamp and bit-offset behavior, including",
        "   width zero/32. Check against the scalar bit-emission semantics before",
        "   timing. This function is about 6.2% of Balanced and 9.5% of compromise.",
        "2. Reduce matcher iteration/bounds bookkeeping while preserving candidate",
        "   order, probe budgets and token semantics. `Matcher::next` and chain",
        "   traversal are major costs; inspect closure sites/counters if needed",
        "   before choosing a rewrite. Existing bulk insertion is not a new spike.",
        "3. Simplify accepted-match range checks using already established bounds,",
        "   retaining full candidate byte validation. `accept` is about 7.1% of",
        "   Balanced on the real set, 13.6% on Chinook and 22.5% on the old sampling",
        "   trap. Include invalid indices, overflow boundaries and overlap witnesses.", "",
        "No production optimization is promoted by this report. Extra research counters",
        "are deferred until narrowing an ambiguous matcher cost requires them. The",
        "new corpus's old compromise gives 1.472× speed but +3.878% bytes, so parameter",
        "tuning alone has not met the main 1.5×/+1% target on these training files.", "",
        "## Limitations and reproduction", "",
        "This pilot has no first-call confidence, RSS or final integrated size results.",
        "Sampling includes startup/priming/packet-write samples and loop-clock overhead;",
        "these must not be treated as production encoder hotspots. Source-line",
        "attribution and one trace per pair are approximate. Only this M5 workload",
        "is measured. Old S9 outliers are regression evidence, not a fresh holdout.", "",
        "[Corpus metadata](../scripts/reports/encoder-corpus.json),",
        "[baseline report](../scripts/reports/encoder-baseline-train.json),",
        "[raw paired ledger](../scripts/reports/encoder-baseline-train-measurements.jsonl.gz)",
        "and [profile evidence](../scripts/reports/encoder-profile.json) retain the",
        "inputs, hashes, source/build provenance, samples and weighting components.", "",
        "```sh", "python3 scripts/encoder_baseline.py --check", "python3 scripts/encoder_corpus.py --check",
        "python3 scripts/test_encoder_tools.py",
        "python3 scripts/encoder_measure.py --out target/encoder-performance/baseline-train-NEW",
        "CARGO_PROFILE_RELEASE_DEBUG=line-tables-only cargo build --locked --release -p deflate-core --example final_bench --features research-tuning --target-dir target/encoder-performance/profiling-build",
        "python3 scripts/encoder_profile.py --out target/encoder-performance/profile-train-NEW",
        "python3 scripts/encoder_profile_report.py --profiles target/encoder-performance/profile-train-NEW --baseline target/encoder-performance/baseline-train-NEW",
        "```", ""]
    (ROOT / "docs/encoder-profile-report.md").write_text("\n".join(lines))
    print(json.dumps({"profiles": len(profiles["rows"]), "verified_rows": len(rows), "coverage": coverage}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=ROOT / "target/encoder-performance/profile-train-v1")
    parser.add_argument("--baseline", type=Path, default=ROOT / "target/encoder-performance/baseline-train-v1")
    parser.add_argument("--out", type=Path, default=ROOT / "scripts/reports")
    args = parser.parse_args()
    run(args.profiles, args.baseline, args.out)
