#!/usr/bin/env python3
"""P5 complete-session statistics and explicit role/common guard decisions."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

from encoder_final_campaign import guard
from encoder_corpus import write_json
from encoder_measure import sha
from search_final_stats import direct, summary


def validate_rows(rows, cases, methods, sessions):
    wanted={(s,c["path"],m) for s in range(sessions) for c in cases for m in methods}
    keys=[(r["session"],r["input"],r["method"]) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=wanted:raise ValueError("missing or duplicate final observation")
    fields=("encode_ns","decode_ns","baseline_encode_ns","baseline_decode_ns","cold_encode_ns","cold_decode_ns","cold_baseline_encode_ns","cold_baseline_decode_ns")
    if any(not math.isfinite(r[f]) or r[f]<=0 for r in rows for f in fields):raise ValueError("invalid final timing")
    sizes=defaultdict(set)
    for r in rows:sizes[r["input"],r["method"]].add((r["packed_bytes"],r["baseline_bytes"],r["packet_sha256"],r["baseline_packet_sha256"]))
    if any(len(values)!=1 for values in sizes.values()):raise ValueError("nondeterministic final output")


def rss_increase(rss, method, reference=None):
    cases=sorted({r["input"] for r in rss if r["method"]==method})
    if not cases:raise ValueError("missing RSS evidence")
    result=[]
    for case in cases:
        candidate=[r["peak_rss_bytes"] for r in rss if r["input"]==case and r["method"]==method and r["side"]=="candidate"]
        baseline=[r["peak_rss_bytes"] for r in rss if r["input"]==case and
            ((r["method"]==method and r["side"]=="baseline") if reference is None else (r["method"]==reference and r["side"]=="candidate"))]
        if len(candidate)!=3 or len(baseline)!=3:raise ValueError("three RSS replicates required for both sides")
        result.append({"input":case,"candidate_median_bytes":statistics.median(candidate),"baseline_median_bytes":statistics.median(baseline),
                       "increase_bytes":statistics.median(candidate)-statistics.median(baseline)})
    return {"cases":result,"maximum_increase_bytes":max(c["increase_bytes"] for c in result)}


def role_guards(metrics, role, common, rss, binary_growth):
    primary=metrics["new-real-test"]
    checks={"warm_speed":primary["session_bootstrap_95pct"]["warm_speed"][0]>=role["warm_speed_lower_95_min"],
        "first_call_speed":primary["session_bootstrap_95pct"]["cold_speed"][0]>=role["first_call_speed_lower_95_min"],
        "aggregate_sizes":all(metrics[scope]["size_vs_balanced"]<=role["aggregate_size_ratio_max"] for scope in ("new-real-test","new-synthetic-test","old-regression")),
        "per_file_sizes":all(metrics[scope]["max_file_size_vs_balanced"]<=role["per_file_size_ratio_max"] for scope in ("new-real-test","new-synthetic-test","old-regression")),
        "decode_times":all(m["session_bootstrap_95pct"][kind][1]<=common["decoder_time_upper_95_ratio_max"] for scope,m in metrics.items() if scope!="tiny"
                           for kind in ("warm_decode_time","cold_decode_time")),
        "tiny_latency":max(r["warm_encode_ns"]/r["warm_baseline_encode_ns"] for r in metrics["tiny"]["per_file"].values())<=common["worst_tiny_warm_median_ratio_max"],
        "rss":rss["maximum_increase_bytes"]<=common["max_per_case_median_process_rss_increase_bytes"],
        "portable_cli_size":binary_growth<=common["portable_release_binary_growth_bytes_max"]}
    return {"checks":checks,"passed":all(checks.values()),"maximum_tiny_warm_median_ratio":max(r["warm_encode_ns"]/r["warm_baseline_encode_ns"] for r in metrics["tiny"]["per_file"].values()),
            "scope":"role baseline stated separately; numerical targets concern primary real scope; size caps cover every non-tiny scope; decode caps cover warm and first-call in every non-tiny scope"}


def run(out):
    frozen=json.loads((out/"freeze.json").read_text());guard(out,frozen)
    completed=json.loads((out/"result.json").read_text())
    if sha(out/"freeze.json")!=completed["freeze_sha256"] or sha(out/"measurements.jsonl")!=completed["measurement_sha256"] or sha(out/"rss.json")!=completed["rss_sha256"]:
        raise ValueError("completed evidence changed")
    rows=[json.loads(line) for line in (out/"measurements.jsonl").read_text().splitlines()]
    cases=json.loads((out/"manifest.json").read_text())["cases"];methods=frozen["methods"]
    contract=frozen["contract"];measurement=contract["measurement"]
    validate_rows(rows,cases,methods,measurement["sessions"])
    seed=measurement["seed"];resamples=measurement["bootstrap_repetitions"]
    scopes=sorted({c["scope"] for c in cases});by_method={m:[r for r in rows if r["method"]==m] for m in methods}
    metrics={name:{scope:summary([r for r in subset if r["scope"]==scope],seed,resamples) for scope in scopes} for name,subset in by_method.items()}
    rss=json.loads((out/"rss.json").read_text());size=json.loads((out/"portable-size.json").read_text())
    roles={};controls={};comparisons={};families={}
    for role,spec in contract["roles"].items():
        name="new-"+role;memory=rss_increase(rss,name)
        evaluated=role_guards(metrics[name],spec,contract["common_guards"],memory,size["binary_growth_bytes"])
        roles[role]={"method":name,"baseline":"original "+spec["baseline"],"metrics":metrics[name],"rss":memory,"guardrails":evaluated}
        controls[role]={}
        for old in contract["controls"]:
            values=metrics[old] if spec["baseline"]=="balanced" else {
                scope:direct([r for r in by_method[old] if r["scope"]==scope],[r for r in by_method["best"] if r["scope"]==scope],seed,resamples) for scope in scopes}
            if spec["baseline"]!="balanced":
                # Guard implementation uses generic baseline fields; labels are
                # restored here while the record explicitly names original Best.
                for m in values.values():
                    for key in tuple(m):
                        if key.endswith("_vs_reference"):m[key.replace("_vs_reference","_vs_balanced")]=m.pop(key)
                    for f in m["per_file"].values():
                        f["warm_baseline_encode_ns"]=f.pop("warm_reference_encode_ns")
            memory_old=rss_increase(rss,old,spec["baseline"])
            controls[role][old]={"baseline":"original "+spec["baseline"],"metrics":values,"rss":memory_old,
                "guardrails":role_guards(values,spec,contract["common_guards"],memory_old,0)}
        eligible=[old for old,v in controls[role].items() if v["guardrails"]["passed"]]
        c=metrics[name]["new-real-test"]
        dominated=[]
        for old in eligible:
            other=controls[role][old]["metrics"]["new-real-test"]
            if other["packed_bytes"]<=c["packed_bytes"] and other["summed_file_medians_ns"]["encode_ns"]<=c["summed_file_medians_ns"]["encode_ns"]:
                dominated.append(old)
        roles[role]["frontier"]={"guard_qualifying_controls":eligible,"dominated_by":dominated,
            "new_point":evaluated["passed"] and not dominated,
            "limitation":"finite frozen workload and measured summed medians; no population or universal superiority claim"}
    for name in ("new-speed","new-compromise","new-size","core-reversal"):
        comparisons[name]={old:{scope:direct([r for r in by_method[name] if r["scope"]==scope],[r for r in by_method[old] if r["scope"]==scope],seed,resamples)
            for scope in scopes} for old in ("miniz1","miniz6","miniz9","best","policy-size","policy-speed")}
        families[name]={}
        for scope in scopes:
            if scope=="tiny":continue
            families[name][scope]={}
            for family in sorted({r["family"] for r in by_method[name] if r["scope"]==scope}):
                subset=[r for r in by_method[name] if r["family"]==family and r["scope"]==scope]
                families[name][scope][family]=summary(subset,seed,resamples)
    core_memory=rss_increase(rss,"core-reversal")
    core=metrics["core-reversal"]
    core_checks={"identical_packets":all(r["packet_sha256"]==r["baseline_packet_sha256"] for r in by_method["core-reversal"]),
        "primary_warm_improvement":core["new-real-test"]["session_bootstrap_95pct"]["warm_speed"][0]>1,
        "primary_first_call_improvement":core["new-real-test"]["session_bootstrap_95pct"]["cold_speed"][0]>1,
        "decode":all(m["session_bootstrap_95pct"][k][1]<=1.2 for scope,m in core.items() if scope!="tiny" for k in ("warm_decode_time","cold_decode_time")),
        "tiny":max(f["warm_encode_ns"]/f["warm_baseline_encode_ns"] for f in core["tiny"]["per_file"].values())<=1.2,
        "rss":core_memory["maximum_increase_bytes"]<=8388608,"binary":size["guard_passed"]}
    report={"freeze_sha256":sha(out/"freeze.json"),"result_sha256":sha(out/"result.json"),"measurement_sha256":completed["measurement_sha256"],"rss_sha256":completed["rss_sha256"],
        "roles":roles,"controls_by_role":controls,"all_methods":metrics,"direct_references":comparisons,"per_family":families,
        "default_core":{"metrics":core,"rss":core_memory,"checks":core_checks,"passed":all(core_checks.values()),
            "scope":"supplementary semantics-preserving default improvement; not attainment of the 1.5x role target"},"portable_size":size,
        "limitations":["bootstrap bounds measure noise across ten sessions, not workload-population generalization","first-call resident input; not cold OS/page/disk caches",
            "RSS is separate whole-process peak, not allocator-event accounting","reference comparisons use matched cases/sessions; only preregistered direct raw miniz_oxide 0.8.9",
            "full correctness/model/CI audit remains separate from numeric qualification"]}
    write_json(out/"statistics.json",report)
    print(json.dumps({"roles":{r:v["guardrails"]["passed"] for r,v in roles.items()},"default_core":report["default_core"]["passed"]}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--campaign",type=Path,required=True)
    run(parser.parse_args().campaign.resolve())
