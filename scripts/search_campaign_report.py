#!/usr/bin/env python3
"""Export complete campaign evidence; no promotion or timing threshold gate."""
import argparse
import gzip
import json
import math
import pathlib
import statistics

from search_campaign import hypervolume, relative_summary
from search_corpus import ROOT
from search_cpu import aggregate, identity
from search_poc import sha
from search_workloads import validate_groups


def scopes(rows, cases):
    names = {pathlib.PurePosixPath(c["path"]).name: c for c in cases}
    return {scope: aggregate([r for r in rows if (names[r["input"]]["family"] == "real") == real])
            for scope, real in (("real", True), ("synthetic", False))}


def check_rows(rows, cases, directory, rounds):
    expected = {pathlib.PurePosixPath(c["path"]).name: c for c in cases}
    if len(rows) != len(expected) or {r["input"] for r in rows} != set(expected):
        raise ValueError("incomplete or duplicate exported measurement matrix")
    for row in rows:
        if row["raw_bytes"] != expected[row["input"]]["bytes"]:
            raise ValueError("wrong raw size")
        for key in ("samples_ns", "baseline_samples_ns"):
            if len(row[key]) != rounds or any(not math.isfinite(v) or v <= 0 for v in row[key]):
                raise ValueError("invalid raw rounds")
        for suffix, hash_key, size_key in ((".deflate", "packed_sha256", "packed_bytes"),
                                         (".baseline.deflate", "baseline_packed_sha256", "baseline_bytes")):
            packed = directory / "streams" / (row["input"] + suffix)
            if packed.stat().st_size != row[size_key] or sha(packed) != row[hash_key]:
                raise ValueError("packed stream evidence changed")


def effects(trials, factorial):
    lookup = {json.dumps(t["config"], sort_keys=True): t for t in trials if "preset" not in t["config"]}
    result = {}
    for scope in ("all", "real", "synthetic"):
        def objective(trial):
            return trial["aggregate"] if scope == "all" else trial[scope]
        comparisons = []
        for axis, levels in factorial.items():
            for new in levels[1:]:
                speeds, sizes = [], []
                for trial in lookup.values():
                    if trial["config"][axis] != levels[0]:
                        continue
                    changed = {**trial["config"], axis: new}
                    other = lookup[json.dumps(changed, sort_keys=True)]
                    before, after = objective(trial), objective(other)
                    speeds.append(before["time_vs_paired_balanced"] / after["time_vs_paired_balanced"])
                    sizes.append(100 * (after["packed_bytes"] / before["packed_bytes"] - 1))
                comparisons.append({"axis": axis, "before": levels[0], "after": new, "contexts": len(speeds),
                                    "median_speed_multiple": statistics.median(speeds),
                                    "speed_range": [min(speeds), max(speeds)],
                                    "median_size_delta_pct": statistics.median(sizes),
                                    "size_delta_pct_range": [min(sizes), max(sizes)]})
        interactions = []
        low, high = factorial["probes"][0], factorial["probes"][-1]
        for trial in lookup.values():
            if not {"dual", "trigram"}.issubset(factorial["index"]) or trial["config"]["probes"] != low or trial["config"]["index"] != "dual":
                continue
            config = trial["config"]
            def time_for(probes, index):
                return objective(lookup[json.dumps({**config, "probes": probes, "index": index}, sort_keys=True)])["time_vs_paired_balanced"]
            interactions.append((time_for(high, "trigram") / time_for(low, "trigram")) /
                                (time_for(high, "dual") / time_for(low, "dual")))
        result[scope] = {"one_axis_pairs": comparisons,
                         "probe_index_interaction": {"probes": [low, high], "contexts": len(interactions),
                         "median_ratio_of_time_multipliers": statistics.median(interactions) if interactions else None,
                         "range": [min(interactions), max(interactions)] if interactions else None}}
    return result


def export(campaign, corpus, output):
    result = json.loads((campaign / "result.json").read_text())
    provenance = json.loads((campaign / "provenance.json").read_text())
    for key in ("source_sha256", "protocol_sha256", "manifest_sha256"):
        if provenance[key] != result[key]:
            raise ValueError("campaign provenance differs from final evidence")
    for name, digest in result["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("measured sources changed before export")
    meta = json.loads((corpus / "manifest.json").read_text())
    validate_groups(corpus, meta)
    if sha(corpus / "manifest.json") != result["manifest_sha256"] or sha(campaign / "finalists.json") != result["finalists_sha256"]:
        raise ValueError("corpus or frozen selection changed")
    output.mkdir(parents=True, exist_ok=True)
    ledger = output / "search-campaign-measurements.jsonl.gz"
    cases = {partition: [c for c in meta["cases"] if c["partition"] == partition] for partition in ("train", "validation")}
    row_count = 0
    studies = []
    factorial_trials = None
    equivalence = None
    with ledger.open("wb") as file, gzip.GzipFile(fileobj=file, filename="", mode="wb", mtime=0) as compressed:
        def record(rows, context):
            nonlocal row_count
            for row in rows:
                compressed.write((json.dumps({**context, **row}, separators=(",", ":"), allow_nan=False) + "\n").encode())
                row_count += 1
        for index, study in enumerate(result["studies"]):
            if study["source_sha256"] != result["source_sha256"] or study["manifest_sha256"] != result["manifest_sha256"] or study["binary_sha256"] != result["binary_sha256"]:
                raise ValueError("study provenance differs")
            if study["git_commit"] != provenance["git_commit"]:
                raise ValueError("campaign parent commit changed")
            if study["axes"] != result["studies"][0]["axes"]:
                raise ValueError("categorical search axes differ between studies")
            compact = {k: v for k, v in study.items() if k not in ("source_sha256", "axes", "fixed_schedule")}
            compact["training"] = []
            points = [(1, 1)]
            curve = []
            reference = result["protocol"]["hypervolume_reference"]
            for trial in study["training"]:
                directory = ROOT / study["directory"] / "train" / trial["id"]
                full = json.loads((directory / "result.json").read_text())
                rows = full["rows"]
                check_rows(rows, cases["train"], directory, study["rounds"])
                if identity(trial["config"]) != trial["id"] or aggregate(rows) != trial["aggregate"]:
                    raise ValueError("training aggregate/config mismatch")
                record(rows, {"phase": "train", "study": index, "trial_id": trial["id"]})
                compact["training"].append({**trial, **scopes(rows, cases["train"])})
                if "preset" not in trial["config"]:
                    points.append((trial["aggregate"]["time_vs_paired_balanced"], trial["aggregate"]["size_vs_balanced"]))
                    curve.append(hypervolume(points, (reference["time_vs_paired_balanced"], reference["size_vs_balanced"])))
            compact["hypervolume_curve"] = curve
            compact["final_hypervolume"] = curve[-1]
            overhead = study["optimizer_setup_seconds"] + study["proposal_seconds"] + (study["optimizer"]["feedback_seconds"] if study["optimizer"] else 0)
            compact["timed_optimizer_overhead_seconds"] = overhead
            compact["timed_optimizer_fraction"] = overhead / study["total_seconds"]
            compact["instantaneous_optimizer_speedup_bound"] = study["total_seconds"] / (study["total_seconds"] - overhead)
            studies.append(compact)
            if study["strategy"] == "fixed":
                factorial_trials = compact["training"]
                fast_id = identity({"preset": "fast"})
                config_id = identity({"probes": 4, "lazy": False, "insert_tail": 16, "index": "dual", "block_tokens": 16384})
                if config_id in {t["id"] for t in factorial_trials}:
                    base = json.loads((ROOT / study["directory"] / "train" / fast_id / "result.json").read_text())
                    equivalent = json.loads((ROOT / study["directory"] / "train" / config_id / "result.json").read_text())
                    before = {r["input"]: r["packed_sha256"] for r in base["rows"]}
                    after = {r["input"]: r["packed_sha256"] for r in equivalent["rows"]}
                    if before != after:
                        raise ValueError("equivalent Fast configuration changed output bytes")
                    equivalence = {"preset": "fast", "config_id": config_id, "cases": len(before),
                                   "all_bytes_equal": before == after,
                                   "interpretation": "finite output equality witness; timing differences are policy representation/codegen or noise, not different search settings"}
        for label, measured in (("validation", result["validation"]), ("direct", result["direct_comparisons"])):
            for measurement in measured:
                phase = label if label == "validation" else "direct-" + measurement["role"]
                directory = campaign / phase / measurement["id"]
                rows = measurement["rows"]
                check_rows(rows, cases["validation"], directory, result["protocol"]["validation_rounds"])
                if relative_summary(rows, measurement["baseline"]) != measurement["aggregate"]:
                    raise ValueError("validation aggregate mismatch")
                record(rows, {"phase": phase, "trial_id": measurement["id"], "baseline": measurement["baseline"]})
    validation = [{k: v for k, v in m.items() if k != "rows"} for m in result["validation"]]
    direct = [{k: v for k, v in m.items() if k != "rows"} for m in result["direct_comparisons"]]
    by_id = {m["id"]: m for m in validation}
    guards = {}
    real_names = {pathlib.PurePosixPath(c["path"]).name for c in cases["validation"] if c["family"] == "real"}
    for role, key in result["finalists"]["representatives"].items():
        measured = next(m for m in result["validation"] if m["id"] == key)
        real_rows = [r for r in measured["rows"] if r["input"] in real_names]
        guards[role] = {"real_size_vs_balanced": by_id[key]["real"]["aggregate"]["size_vs_balanced"],
                        "max_real_file_size_vs_balanced": max(r["packed_bytes"] / r["baseline_bytes"] for r in real_rows),
                        "passes_real_file_size_guard": all(r["packed_bytes"] / r["baseline_bytes"] <= result["protocol"]["guardrails"]["maximum_real_file_size_vs_balanced"] for r in real_rows)}
        if role == "balanced":
            guards[role]["passes_real_aggregate_size_guard"] = guards[role]["real_size_vs_balanced"] <= result["protocol"]["guardrails"]["aggregate_compromise_size_vs_balanced"]
    report = {"schema_version": 1, "protocol": result["protocol"], "protocol_sha256": result["protocol_sha256"],
              "categorical_search_axes": result['studies'][0]['axes'],
              "categorical_configurations": math.prod(len(values) for values in result['studies'][0]['axes'].values()),
              "source_sha256": result["source_sha256"], "binary_sha256": result["binary_sha256"],
              "git_parent_commit": provenance["git_commit"],
              "source_provenance": "measured working-tree files include uncommitted research tooling; source_sha256 identifies the measured revision, not the parent commit alone",
              "analysis_source_sha256": sha(pathlib.Path(__file__)), "corpus": meta,
              "manifest_sha256": result["manifest_sha256"], "studies": studies,
              "finalists": result["finalists"], "finalists_sha256": result["finalists_sha256"],
              "validation": validation, "direct_comparisons": direct, "guardrails": guards,
              "factorial_effects": effects(factorial_trials, result["protocol"]["factorial"]),
              "default_equivalent_control": equivalence,
              "memory": result["memory"], "total_seconds": result["total_seconds"],
              "raw_ledger": str(ledger.relative_to(ROOT)), "raw_ledger_sha256": sha(ledger), "raw_rows": row_count,
              "reference": "miniz_oxide 0.8.9, Cargo.lock; direct paired levels 1/6/9",
              "test_partition_measured": False, "promotion": "none",
              "limitations": ["real holdout was visible previously; regression evidence only",
                 "the finite seed/evaluation budget is a bounded pilot, not global optimality",
                 "unique evaluation budgets are equal; elapsed time is reported, not a matched wall-time stop budget",
                 "training uses mixed 256 KiB regimes/chunks; validation uses full real files",
                 "bootstrap resamples workload groups and paired rounds; not a guarantee for unmeasured workloads",
                 "RSS measures whole encode processes on two cases, not all-trial allocation or a third optimized objective",
                 "optimizer replacement bound applies to timed CPU setup/proposals/feedback; no trained GPU model measured",
                 "no production preset promotion or fresh final test"]}
    report_path = output / "search-campaign.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(report_path), "raw_rows": row_count, "ledger_bytes": ledger.stat().st_size}))
    return report


def render(report):
    protocol = report["protocol"]
    training = [c for c in report["corpus"]["cases"] if c["partition"] == "train"]
    validation = [c for c in report["corpus"]["cases"] if c["partition"] == "validation"]
    nfactor = math.prod(len(levels) for levels in protocol["factorial"].values())
    measured_by_id = {m["id"]: m for m in report["validation"]}
    speed = measured_by_id[report["finalists"]["representatives"]["speed"]]["real"]["aggregate"]
    small = measured_by_id[report["finalists"]["representatives"]["size"]]["real"]["aggregate"]
    compromise = measured_by_id[report["finalists"]["representatives"]["balanced"]]["real"]["aggregate"]
    equivalence = report.get("default_equivalent_control")
    lines = ["# S2/S3: mixed workloads, CPU optimizers and measured memory", "",
             f"This frozen campaign compares {len(protocol['strategies'])} CPU search strategies across {len(protocol['seeds'])} seeds,",
             "then checks training-selected finalists on full real files and larger synthetic",
             "cases. Production presets are unchanged. The real holdout was previously",
             "visible, so these are regression results rather than fresh final-test evidence.", "",
             f"On real validation, the training speed representative reaches {speed['speed_vs_paired_balanced']:.2f}× Balanced throughput",
             f"with {100 * (speed['size_vs_balanced'] - 1):+.2f}% output size. The size representative changes output by",
             f"{100 * (small['size_vs_balanced'] - 1):+.2f}% at {small['speed_vs_paired_balanced']:.2f}× throughput. The training compromise",
             f"reaches {compromise['speed_vs_paired_balanced']:.2f}× with {100 * (compromise['size_vs_balanced'] - 1):+.2f}% output size.", "",
             "## Frozen experiment", "",
             f"[The protocol](../scripts/search_protocol.json) fixes {protocol['configured_trials_per_strategy_seed']} unique configured",
             f"evaluations per strategy/seed, {protocol['training_rounds']} rounds of at least {protocol['training_minimum_batch_ms']} ms and a separate",
             f"{nfactor}-configuration factorial. Strategy order rotates across seeds. Finalists are",
             f"frozen before {protocol['validation_rounds']} validation rounds of at least {protocol['validation_minimum_batch_ms']} ms and direct reference checks.", "",
             f"Training uses {sum(c['family'] != 'real' for c in training)} synthetic {protocol['training_chunk_bytes'] // 1024} KiB regimes and {sum(c['family'] == 'real' for c in training)} real source-file chunks,",
             f"{sum(c['bytes'] for c in training) / 1e6:.2f} MB total. Validation has {sum(c['family'] != 'real' for c in validation)} larger synthetic cases and {sum(c['family'] == 'real' for c in validation)} full real files,",
             f"{sum(c['bytes'] for c in validation) / 1e6:.2f} MB total. Original source-file train/holdout assignments are preserved.",
             "Fourteen full synthetic test cases remain reserved and were never encoded.", "",
             "The CPU strategies are random, the earlier Pareto-mutation heuristic and",
             "[Optuna 4.5.0 NSGA-II](https://optuna.readthedocs.io/en/v4.5.0/reference/samplers/generated/optuna.samplers.NSGAIISampler.html)",
             "with population 16 and categorical axes. Duplicate proposals reuse verified",
             "training scores; the budget counts unique encoder evaluations. Failed trials",
             "abort and receive no invented objective. Native encode timing includes allocation",
             "and excludes I/O/decoder checks. Both candidate and baseline streams pass",
             "deflate-core, miniz_oxide and exact-consuming zlib checks.", "",
             f"The optimizer samples {report['categorical_configurations']} joint configurations from the recorded",
             "categorical axis levels. This is a discrete subset of the adapter's wider",
             "valid integer ranges; the report retains the levels alongside the factorial.", "",
             "## Optimizer comparison on training", "",
             "Hypervolume minimizes normalized time and size, with fixed reference (4, 1.5)",
             "and Balanced anchor (1, 1). Points outside that box do not contribute. Stored",
             "and reference encoders are excluded. Values summarize this measured budget;",
             "they do not certify optimizer superiority or global optimality.", "",
             "| Strategy | Hypervolume median [min, max] | Recorded study seconds median | Timed optimizer fraction max |",
             "| --- | ---: | ---: | ---: |"]
    for strategy in report["protocol"]["strategies"]:
        studies = [s for s in report["studies"] if s["strategy"] == strategy]
        hv = [s["final_hypervolume"] for s in studies]
        lines.append(f"| {strategy} | {statistics.median(hv):.4f} [{min(hv):.4f}, {max(hv):.4f}] | "
                     f"{statistics.median(s['total_seconds'] for s in studies):.2f} | "
                     f"{100 * max(s['timed_optimizer_fraction'] for s in studies):.3f}% |")
    lines += ["", "Recorded study time includes the cached build, proposals, encoder evaluation,",
              "oracle checks and in-run integrity guards. Initial process startup and",
              "manifest/provenance preparation precede that study clock; corpus generation",
              "and downloads are separate. The campaign wall time also includes full-file",
              "validation, bootstrap computation, reference checks and RSS runs. Unique",
              "evaluation budgets are matched; wall-time stop budgets are not. This study",
              "does not establish time-to-target superiority.", "",
              "## Frozen representatives on real validation", "",
              "Representatives are chosen from training only. Other per-study role",
              "finalists and prior synthetic sentinels are retained in the evidence. Speed",
              "intervals resample real source files and paired rounds; they reflect workload",
              "variation as well as timing noise.", "",
              "| Role | Configuration | Speed vs paired Balanced [95% interval] | Size vs Balanced | Max file size change |",
              "| --- | --- | ---: | ---: | ---: |"]
    by_id = {m["id"]: m for m in report["validation"]}
    for role, key in report["finalists"]["representatives"].items():
        measured = by_id[key]
        agg, ci = measured["real"]["aggregate"], measured["real"]["confidence"]["speed_multiple_95pct"]
        config = measured["config"]
        label = config.get("preset") or f"p{config['probes']}, {'lazy' if config['lazy'] else 'greedy'}, tail{config['insert_tail']}, {config['index']}, split{config['block_tokens']}"
        lines.append(f"| {role} | {label} | {agg['speed_vs_paired_balanced']:.2f}× [{ci[0]:.2f}, {ci[1]:.2f}] | "
                     f"{100 * (agg['size_vs_balanced'] - 1):+.2f}% | "
                     f"{100 * (report['guardrails'][role]['max_real_file_size_vs_balanced'] - 1):+.2f}% |")
    compromise_guard = report['guardrails']['balanced']['passes_real_aggregate_size_guard']
    failed_file_guards = [role for role, guard in report['guardrails'].items() if not guard['passes_real_file_size_guard']]
    lines += ["", f"The predeclared compromise aggregate size guard (+{100 * (protocol['guardrails']['aggregate_compromise_size_vs_balanced'] - 1):.0f}%) "
              f"{'passes' if compromise_guard else 'fails'} on real validation.",
              f"The per-file size guard (+{100 * (protocol['guardrails']['maximum_real_file_size_vs_balanced'] - 1):.0f}%) "
              + ("fails for: " + ', '.join(failed_file_guards) + "." if failed_file_guards else "passes for all three representatives."),
              "These guardrails report transfer failures; they do not trigger a new selection",
              "using the validation results."]
    control = next(m for m in report['validation'] if m['config'] == {'preset': 'balanced'})['real']
    ci = control['confidence']['speed_multiple_95pct']
    lines += ["", f"The Balanced-vs-itself real control measures {control['aggregate']['speed_vs_paired_balanced']:.4f}× "
              f"[{ci[0]:.4f}, {ci[1]:.4f}] with identical encoded sizes. This is a control for",
              "paired measurement variation in this run, not a bound on future timing noise."]
    best = next(m for m in report['validation'] if m['config'] == {'preset': 'best'})['real']['aggregate']
    dominated = (best['size_vs_balanced'] <= small['size_vs_balanced'] and best['time_vs_paired_balanced'] <= small['time_vs_paired_balanced']
                 and (best['size_vs_balanced'] < small['size_vs_balanced'] or best['time_vs_paired_balanced'] < small['time_vs_paired_balanced']))
    lines += ["", f"Production Best changes real output size by {100 * (best['size_vs_balanced'] - 1):+.2f}% "
              f"at {best['speed_vs_paired_balanced']:.2f}× Balanced speed."]
    if dominated:
        lines += ["It dominates the training size representative on these measured normalized",
                  "aggregates. This is a transfer failure, not a newly better compression",
                  "policy. The speed comparison uses separate paired-Balanced sessions;",
                  "the compressed sizes are exact. The frozen representative remains unchanged."]
    sentinels = [m for m in report['validation'] if 'preset' not in m['config'] and 'reference' not in m['config']
                 and 'prior synthetic sentinel' in report['finalists']['origins'][m['id']]]
    if sentinels:
        lines += ["", "## Prior synthetic winners on expanded validation", "",
                  "These configurations were frozen from the earlier S1 pilot. The columns",
                  "below are measured in this campaign on its larger synthetic validation",
                  "cases and full real files, rather than comparisons between separate runs.", "",
                  "| Configuration | Synthetic speed vs Balanced | Synthetic size change | Real speed vs Balanced | Real size change |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for measured in sentinels:
            c = measured['config']
            label = f"p{c['probes']}, {'lazy' if c['lazy'] else 'greedy'}, tail{c['insert_tail']}, {c['index']}, split{c['block_tokens']}"
            real, synthetic = (measured[scope]['aggregate'] for scope in ('real', 'synthetic'))
            lines.append(f"| {label} | {synthetic['speed_vs_paired_balanced']:.2f}× | "
                         f"{100 * (synthetic['size_vs_balanced'] - 1):+.2f}% | {real['speed_vs_paired_balanced']:.2f}× | "
                         f"{100 * (real['size_vs_balanced'] - 1):+.2f}% |")
    lines += ["", "## Direct paired reference checks on real validation", "",
              "Each row directly alternates the selected encoder and the named miniz level",
              "in the same worker. These are direct measurements, rather than ratios of",
              "separate benchmark runs.", "",
              "| Role | Reference | Speed multiple [95% interval] | Size change |",
              "| --- | --- | ---: | ---: |"]
    for measured in report["direct_comparisons"]:
        agg, ci = measured["real"]["aggregate"], measured["real"]["confidence"]["speed_multiple_95pct"]
        lines.append(f"| {measured['role']} | {measured['baseline']} | {agg['speed_vs_reference']:.2f}× "
                     f"[{ci[0]:.2f}, {ci[1]:.2f}] | {100 * (agg['size_vs_reference'] - 1):+.2f}% |")
    lines += ["", "## Controlled interactions on real training chunks", "",
              "The factorial crosses probes 1/4/64/512, lazy mode, tails 0/4/16/32,",
              "dual/trigram and splits 1024/16384. Each comparison changes one axis while",
              "holding every other axis fixed. Medians below are across those contexts;",
              "their ranges in the JSON report are context variation, not confidence intervals.", "",
              "| Axis change | Matched contexts | Median speed multiple | Median size change |",
              "| --- | ---: | ---: | ---: |"]
    for effect in report["factorial_effects"]["real"]["one_axis_pairs"]:
        lines.append(f"| {effect['axis']}: {effect['before']} → {effect['after']} | {effect['contexts']} | "
                     f"{effect['median_speed_multiple']:.2f}× | {effect['median_size_delta_pct']:+.2f}% |")
    interaction = report["factorial_effects"]["real"]["probe_index_interaction"]
    ratio = interaction['median_ratio_of_time_multipliers']
    lines += ["", (f"The median trigram/dual ratio of the time cost of increasing probes from {interaction['probes'][0]} "
                   f"to {interaction['probes'][1]} is {ratio:.2f}× across {interaction['contexts']} contexts."
                   if ratio is not None else "This factorial contains no paired probe/index interaction contexts."),
              "Larger probe budgets are not assumed to improve either size or throughput",
              "on every workload.", "",
              (f"The p4/greedy/tail16/dual/16384 control matched Fast output bytes on {equivalence['cases']} training cases."
               if equivalence else "No Fast-equivalent configuration was part of this factorial."),
              "Timing differences among equivalent settings reflect representation/codegen",
              "and measurement variation.", "",
              "## Memory and GPU decision", "",
              f"Memory uses {protocol['memory_process_repetitions']} fresh single-encode processes per finalist on the largest",
              "real and synthetic validation cases. Peak RSS includes runtime, input, output",
              "and file I/O; decoding and timing loops run outside these processes. Darwin",
              "units follow the current local getrusage(2) manual (bytes), and the parser",
              "also supports GNU time KiB on Linux. RSS samples/ranges are retained, while",
              "the 192/384 KiB table capacities remain a separate analytical quantity.", "",
              "| Role | Largest real case median RSS, MiB | Largest synthetic case median RSS, MiB |",
              "| --- | ---: | ---: |"]
    memory = report["memory"]["measurements"]
    for role, key in report["finalists"]["representatives"].items():
        values = [m["median_rss_bytes"] / (1 << 20) for m in memory if m["id"] == key]
        lines.append(f"| {role} | {values[0]:.2f} | {values[1]:.2f} |")
    timed = [s for s in report["studies"] if s["strategy"] != "fixed"]
    bound = max(s["instantaneous_optimizer_speedup_bound"] for s in timed)
    lines += ["", f"Even deleting the timed CPU setup/proposal/feedback sections entirely would",
              f"speed these search runs by at most {bound:.4f}×. This is a generous bound",
              "for replacing those sections, not a trained-surrogate or GPU-encoder result.",
              "The earlier GPU scoring spike still describes kernel capacity only. Model",
              "fitting, context policies and GPU proposal batches need their own evidence.", "",
              "## Decision and next experiments", "",
              "Keep the training-selected points as experimental results. This campaign",
              "does not establish a preset promotion: the size guards and production controls",
              "expose transfer failures, and no fresh final test or other hardware was used.", "",
              "The next S5 baseline should select among fixed configurations and production",
              "presets using cheap workload features, with source/family-grouped cross-validation",
              "and feature/selection overhead charged to encoder time. The five-axis adapter",
              "uses fixed splits and explicit index choices; it does not reproduce Balanced's",
              "classifier or Best's adaptive split callback as configurable policies. Expand",
              "method choices in separate controlled spikes before assuming a stronger",
              "optimizer can recover those behaviors. S7's short encoded-cost oracle can",
              "then test a new parsing hypothesis. Fit a latent/GPU surrogate only after",
              "the simple context baseline has prediction and calibration evidence.", "",
              "## Evidence and reproduction", "",
              "[Full report](../scripts/reports/search-campaign.json) links the deterministic",
              "[gzip JSONL ledger](../scripts/reports/search-campaign-measurements.jsonl.gz)",
              f"with {report['raw_rows']} candidate rows, raw candidate/baseline rounds and both",
              "stream hashes. Source/binary/corpus hashes, dependency versions, every training",
              "configuration and frozen selection are retained. Packed streams and original",
              "data remain under ignored target/.", "",
              f"The recorded Git parent is `{report['git_parent_commit']}`. Measurements include",
              "then-uncommitted research tooling; the source SHA-256 map identifies the",
              "measured files. The parent commit alone does not reproduce this experiment.", "",
              "Local verification passed 192 feature-enabled Rust tests, 25 research-tool",
              "integrity/adapter tests and 232 unchanged preset stream hashes checked by all",
              "three decoders. Format and all-feature Clippy checks passed. CI additionally",
              "gates the Lean model/axioms, differential/framing harnesses and five fuzz targets.", "",
              "```sh", "make research-check", "make research-campaign",
              "python3 scripts/search_campaign_report.py --campaign target/search/campaigns/RUN", "```", "",
              "The optional campaign requires Python 3.12+. `make research-campaign`",
              "installs pinned optional CPU research dependencies in",
              "a local venv and fetches author-hosted corpus archives into target/. Core",
              "runtime dependencies, production policies and the Lean model are unchanged.", "",
              f"{len(protocol['seeds'])} seeds and {protocol['configured_trials_per_strategy_seed']} unique evaluations per strategy are a bounded comparison. A fresh",
              "final test, additional hardware and memory coverage precede production",
              "promotion. The separate speed, compression and compromise points remain",
              "experimental until those gates are satisfied.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=pathlib.Path, required=True)
    parser.add_argument("--corpus", type=pathlib.Path, default=ROOT / "target/search/corpus-mixed-s2")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "scripts/reports")
    parser.add_argument("--doc", type=pathlib.Path, default=ROOT / "docs/cpu-search-campaign-report.md")
    args = parser.parse_args()
    report = export(args.campaign.resolve(), args.corpus.resolve(), args.out.resolve())
    args.doc.write_text(render(report))


if __name__ == "__main__":
    main()
