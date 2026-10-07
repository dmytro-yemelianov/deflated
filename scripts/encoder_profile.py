#!/usr/bin/env python3
"""Encoder-only sampling on training/regression inputs, with inline attribution."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import DEFAULT_OUT as CORPUS_OUT, ROOT, write_json
from encoder_measure import inputs, sha
from profile_attrib import BASE, CORE, col
from search_poc import decode_exact

DEFAULT_BINARY = ROOT / "target/encoder-performance/profiling-build/release/examples/final_bench"


def source_hashes():
    tracked = subprocess.check_output(["git", "ls-files", "crates/deflate-core", "Cargo.toml", "Cargo.lock"], cwd=ROOT, text=True).splitlines()
    names = [n for n in tracked if n.endswith((".rs", ".toml", ".lock"))]
    names += ["scripts/encoder_profile.py", "scripts/encoder_measure.py", "scripts/profile_attrib.py",
              "scripts/encoder_baseline.py", "scripts/encoder_corpus.py", "scripts/search_poc.py"]
    return {name: sha(ROOT / name) for name in names}


def symbol_labels(lines):
    labels = []
    for line in lines:
        if not line.strip():
            continue
        name = re.sub(r"::h[0-9a-f]{16}", "", line.split(" (in")[0]).strip()
        location = re.search(r"\(([^():]+\.rs):(\d+)\)", line)
        file = Path(location[1]).name if location else None
        if name.startswith(("miniz_oxide::", "_$LT$miniz_oxide.")) or file == "core.rs":
            owner = "miniz"
        elif name.startswith(("deflate_core::", "_$LT$deflate_core.")) or file in CORE:
            owner = "deflate-core"
        else:
            owner = "binary-other"
        if name.startswith("0x") or "???" in name:
            owner = "unresolved"
        label = owner + "/" + (file + "::" if file else "") + name
        labels.append((owner, label))
    return labels or [("unresolved", "unresolved/binary-address")]


def attribute(profile, binary, cache):
    with gzip.open(profile, "rt") as stream:
        data = json.load(stream)
    inclusive, exclusive, owners = collections.Counter(), collections.Counter(), collections.Counter()
    contexts = collections.Counter()
    samples, missing = 0, 0
    for thread in data["threads"]:
        stacks = col(thread["stackTable"], "frame")
        prefixes = col(thread["stackTable"], "prefix")
        addresses = col(thread["frameTable"], "address")
        functions = col(thread["frameTable"], "func")
        resources = thread["funcTable"]["resource"]
        libraries = thread["resourceTable"]["lib"]

        def resolve(frame):
            resource = resources[functions[frame]]
            index = libraries[resource] if resource is not None and resource >= 0 else None
            lib = data["libs"][index]["name"] if index is not None and index >= 0 else "unknown"
            address = addresses[frame]
            if lib != binary.name:
                return [("library", "library/" + lib)]
            key = (lib, address)
            if key not in cache:
                output = subprocess.check_output(["atos", "-i", "-o", str(binary), "-l", hex(BASE), hex(BASE + address)], text=True)
                cache[key] = symbol_labels(output.splitlines())
            return cache[key]

        for stack in col(thread["samples"], "stack"):
            if stack is None:
                missing += 1
                continue
            samples += 1
            leaf = resolve(stacks[stack])[0]
            exclusive[leaf[1]] += 1
            owners[leaf[0]] += 1
            chain = set()
            seen = set()
            context = None
            while stack is not None and stack >= 0:
                if stack in seen:
                    raise ValueError("cyclic profile stack")
                seen.add(stack)
                labels = [(owner, label) for owner, label in resolve(stacks[stack]) if owner in ("deflate-core", "miniz")]
                if context is None and labels:
                    context = labels[0][1]
                chain.update(label for _, label in labels)
                stack = prefixes[stack]
            inclusive.update(chain)
            contexts[context or leaf[1]] += 1
    if not samples:
        raise ValueError("profile contains no attributed samples")
    pct = lambda counts: {k: round(100 * v / samples, 3) for k, v in counts.most_common()}
    return {"samples": samples, "null_stack_samples": missing,
            "inclusive_samples": dict(inclusive), "exclusive_samples": dict(exclusive),
            "inclusive_pct": pct(inclusive), "exclusive_pct": pct(exclusive),
            "nearest_encoder_caller_samples": dict(contexts), "nearest_encoder_caller_pct": pct(contexts),
            "exclusive_owner_pct": pct(owners), "accounting": "inline chains plus sampled ancestors inclusive; first inline frame exclusive; inclusive shares overlap"}


def run(out, corpus, baseline, binary, seconds, case_limit, method_names):
    out = out.resolve()
    if platform.system() != "Darwin" or not shutil.which("samply") or not shutil.which("atos"):
        raise ValueError("macOS samply and atos required")
    if seconds <= 0 or case_limit < 1:
        raise ValueError("positive profile duration and case count required")
    frozen_baseline = check_baseline(baseline)
    cases = inputs(corpus)[:case_limit]
    methods = json.loads((baseline / "methods.json").read_text())
    if not method_names or any(name not in methods for name in method_names):
        raise ValueError("unknown profile method")
    subprocess.run(["dsymutil", str(binary)], check=True)
    frozen_sources = source_hashes()
    binary_hash = sha(binary)
    out.mkdir(parents=True, exist_ok=False)
    rows, cache, current = [], {}, None
    started = time.perf_counter()
    protocol = {"seconds": seconds, "cases": cases, "methods": method_names,
                "binary_path": str(binary), "binary_sha256": binary_hash, "source_sha256": frozen_sources,
                "corpus_manifest_sha256": sha(corpus / "manifest.json"), "baseline_metadata_sha256": sha(baseline / "baseline.json"),
                "build": {"profile": "release", "debug": "line-tables-only", "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip()},
                "samply": subprocess.check_output(["samply", "--version"], text=True).strip(),
                "purpose": "sampling, not benchmark timing; inputs resident before encode loop; no decoder inside sampler"}
    write_json(out / "protocol.json", protocol)
    try:
        for index, case in enumerate(cases):
            raw = Path(case["raw_path"]).read_bytes()
            for name in method_names:
                print("profile", index, case["source_group"], name, flush=True)
                current = {"case": case["source_group"], "method": name}
                method = methods[name]["worker"]
                golden = out / "golden"
                subprocess.check_output([str(baseline / "final_bench"), "cold", case["raw_path"], str(golden), "1", method, "0"], text=True)
                expected = (golden / "candidate.deflate").read_bytes()
                decode_exact(expected, raw)
                profile = out / (f"{index:02d}-" + name + ".json.gz")
                output = subprocess.check_output(["samply", "record", "--save-only", "--unstable-presymbolicate", "-o", str(profile), "--",
                    str(binary), "profile", case["raw_path"], str(out / "current-streams"), str(round(seconds * 1000)), method, "0"],
                    text=True, stderr=subprocess.PIPE, timeout=max(60, seconds + 30))
                packet = (out / "current-streams" / "candidate.deflate").read_bytes()
                if packet != expected:
                    raise ValueError("profile worker changed original packet")
                measurements = attribute(profile, binary, cache)
                row = {"case": case, "method": name, "native": json.loads(output), "packet_sha256": sha(out / "current-streams/candidate.deflate"),
                       "profile_path": str(profile.relative_to(ROOT)), "profile_sha256": sha(profile), **measurements}
                rows.append(row)
                write_json(out / "progress.json", {"completed": len(rows), "total": len(cases) * len(method_names), "rows": rows})
        if source_hashes() != frozen_sources or sha(binary) != binary_hash or check_baseline(baseline) != frozen_baseline:
            raise ValueError("profile sources or binary changed")
        write_json(out / "result.json", {"protocol": protocol, "rows": rows, "elapsed_seconds": time.perf_counter() - started,
                   "limitations": ["process startup, initial priming and packet write can contribute samples", "sampler clock overhead is not encoder cost", "one profile per method/input; not performance confidence", "atos attribution may miss source frames"]})
        print("profile complete", len(rows), "profiles", len(cache), "resolved addresses", flush=True)
    except BaseException as error:
        write_json(out / "failed.json", {"current": current, "completed": len(rows), "error": str(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=CORPUS_OUT)
    parser.add_argument("--baseline", type=Path, default=BASELINE_OUT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--case-limit", type=int, default=11)
    parser.add_argument("--methods", nargs="+", default=["balanced", "best", "miniz6", "bayesian-compromise"])
    args = parser.parse_args()
    run(args.out, args.corpus, args.baseline, args.binary, args.seconds, args.case_limit, args.methods)
