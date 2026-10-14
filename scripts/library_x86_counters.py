#!/usr/bin/env python3
"""Linux/x86-64 counter diagnostics for the library decoders (v13).

references: build the pinned zlib-ng/libdeflate sources as Linux shared
            libraries, verifying archive hashes against the published lock.
            Writes the build-receipt.json layout library_bench.py expects.
counters:   perf stat (user-mode) over warm reuse loops minus a one-decode
            cold run, per decoder x packet x frame, normalized per decoded byte.
record:     perf record on one worker/packet, then resolve sampled PCs to
            inline chains and v10-style categories (core binary only).

Historical macOS helpers are left unchanged. This is diagnostic evidence on a
shared host, not release evidence.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RELEASES = {
    "zlib-ng": ("zlib-ng/zlib-ng", "2.3.3", ["-DZLIB_COMPAT=OFF", "-DZLIB_ENABLE_TESTS=OFF"]),
    "libdeflate": ("ebiggers/libdeflate", "v1.26", ["-DLIBDEFLATE_BUILD_GZIP=OFF", "-DLIBDEFLATE_BUILD_TESTS=OFF"]),
}
GROUPS = {
    "branch": "cycles:u,instructions:u,branches:u,branch-misses:u",
    "memory": "cycles:u,instructions:u,L1-dcache-load-misses:u,LLC-load-misses:u",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def out(command, **kwargs):
    return subprocess.check_output([str(x) for x in command], text=True, **kwargs)


def references(args):
    lock = json.loads(args.source_lock.read_text())
    receipts = {}
    for name in args.codec:
        repo, release, options = RELEASES[name]
        directory = (args.out / name).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{release}"
        archive = directory / "source.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
        if sha(archive) != lock[name]["archive_sha256"]:
            raise RuntimeError(f"{name}: source archive differs from the published lock")
        with tarfile.open(archive) as bundle:
            roots = {Path(m.name).parts[0] for m in bundle.getmembers()}
            if len(roots) != 1:
                raise RuntimeError("unexpected archive roots")
            # Python 3.11.2 lacks extraction filters: reject traversal and
            # anything other than regular files, directories and in-tree links.
            for member in bundle.getmembers():
                parts = Path(member.name).parts
                if member.name.startswith("/") or ".." in parts or not (
                        member.isfile() or member.isdir() or member.issym()):
                    raise RuntimeError(f"unsafe archive member {member.name}")
                if member.issym() and (member.linkname.startswith("/") or
                                       ".." in Path(member.linkname).parts):
                    raise RuntimeError(f"unsafe archive link {member.name}")
            bundle.extractall(directory / "unpacked")
        source = directory / "source"
        (directory / "unpacked" / roots.pop()).rename(source)
        commands = [["cmake", "-S", str(source), "-B", str(directory / "build"), "-G", "Ninja",
                     "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON",
                     "-DCMAKE_C_COMPILER=/usr/bin/clang", "-DCMAKE_CXX_COMPILER=/usr/bin/clang++",
                     "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG", "-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG",
                     "-DCMAKE_INSTALL_LIBDIR=lib", f"-DCMAKE_INSTALL_PREFIX={directory / 'install'}", *options],
                    ["cmake", "--build", str(directory / "build"), "--parallel", "4"],
                    ["cmake", "--install", str(directory / "build")]]
        env = {k: v for k, v in os.environ.items()
               if k not in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "CXX", "CMAKE_PREFIX_PATH")}
        for index, command in enumerate(commands):
            with (directory / f"step{index}.log").open("w") as log:
                subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        libraries = {str(p.relative_to(directory)): sha(p)
                     for p in sorted((directory / "install/lib").glob("*.so*")) if not p.is_symlink()}
        if not libraries:
            raise RuntimeError("no installed shared library")
        receipt = {"schema_version": 1, "codec": name, "release": release, "url": url,
                   "archive_sha256": sha(archive), "compiler": out(["clang", "--version"]).strip(),
                   "host": platform.platform(), "commands": commands, "libraries": libraries,
                   "cmake_cache_sha256": sha(directory / "build/CMakeCache.txt"),
                   "status": "Linux x86-64 diagnostic rebuild of the locked source archive"}
        (directory / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        receipts[name] = receipt
        print(json.dumps({"codec": name, "libraries": libraries}), flush=True)


def worker_call(binary, codec, mode, frame, packet, output, minimum, expected):
    return [binary, mode, codec, "balanced" if codec == "core" else "6", frame, packet, output,
            str(minimum), str(expected)]


def perf_stat(cpu, events, command, scratch):
    stat = scratch / "stat.csv"
    stdout = out(["taskset", "-c", cpu, "perf", "stat", "-x", ",", "-o", stat, "-e", events, "--", *command])
    values = {}
    for line in stat.read_text().splitlines():
        fields = line.split(",")
        if len(fields) < 5 or line.startswith("#"):
            continue
        value, event, running = fields[0], fields[2], fields[4]
        if value.startswith("<"):
            raise RuntimeError(f"event {event} not counted: {value}")
        values[event.removesuffix(":u")] = {"count": float(value), "pct_running": float(running or 100)}
    return stdout, values


def counters(args):
    run = json.loads((args.measure_run / "report.json").read_text())
    packets = {}
    for row in run["rows"]:
        packets[row["path"]] = {k: row[k] for k in ("case", "frame", "encoder", "raw_bytes", "raw_sha256", "path")}
    methods = [("core", args.core, "core"), ("accel", args.accel, "core")]
    if args.extra:
        for item in args.extra:
            label, binary = item.split("=", 1)
            methods.append((label, Path(binary), "core"))
    methods += [(c, args.workers / f"{c}-decode", c) for c in ["zlib-ng", "libdeflate"]]
    scratch = args.out.resolve()
    scratch.mkdir(parents=True, exist_ok=False)
    rows = []
    for repeat in range(args.repeats):
        for packet in sorted(packets.values(), key=lambda p: p["path"]):
            for method, binary, codec in methods[repeat % len(methods):] + methods[:repeat % len(methods)]:
                for group, events in GROUPS.items():
                    output = scratch / "decoded"
                    _, cold = perf_stat(args.cpu, events, worker_call(
                        binary.resolve(), codec, "context-cold", packet["frame"], packet["path"], output, 0,
                        packet["raw_bytes"]), scratch)
                    stdout, warm = perf_stat(args.cpu, events, worker_call(
                        binary.resolve(), codec, "context-warm", packet["frame"], packet["path"], output,
                        args.minimum_ns, packet["raw_bytes"]), scratch)
                    if sha(output) != packet["raw_sha256"]:
                        raise RuntimeError("decoded output mismatch")
                    sample = json.loads(stdout)
                    calls = sample["decode_iterations"]
                    per_call = {e: (warm[e]["count"] - cold[e]["count"]) / calls for e in warm}
                    rows.append({**packet, "method": method, "group": group, "repeat": repeat,
                                 "iterations": calls, "decode_ns": sample["decode_ns"],
                                 "per_call": per_call,
                                 "min_pct_running": min(v["pct_running"] for v in [*warm.values(), *cold.values()])})
        print(f"repeat {repeat + 1}/{args.repeats}: {len(rows)} rows", flush=True)
    report = {"schema_version": 1, "study": "library-decode-v13-x86-counters", "cpu": args.cpu,
              "events": GROUPS, "minimum_ns": args.minimum_ns, "repeats": args.repeats,
              "method": "user-mode perf stat; warm reuse loop minus one-decode cold run, divided by loop calls",
              "binaries": {m: {"path": str(b), "sha256": sha(b)} for m, b, _ in methods},
              "measure_run_sha256": sha(args.measure_run / "report.json"),
              "perf": out(["perf", "--version"]).strip(), "kernel": platform.release(),
              "controller_sha256": sha(Path(__file__)), "summary": summarize(rows), "rows": rows}
    (scratch / "counters.json").write_text(json.dumps(report, indent=2) + "\n")
    for line in report["summary"]:
        print(json.dumps(line))


def summarize(rows):
    result = []
    for frame in ["raw", "gzip"]:
        for method in sorted({r["method"] for r in rows}):
            selected = [r for r in rows if r["frame"] == frame and r["method"] == method]
            keys = sorted({(r["case"], r["encoder"]) for r in selected})
            totals = collections.Counter()
            byte_count = 0
            for key in keys:
                per = [r for r in selected if (r["case"], r["encoder"]) == key]
                byte_count += per[0]["raw_bytes"]
                for event in {e for r in per for e in r["per_call"]}:
                    values = [r["per_call"][event] for r in per if event in r["per_call"]]
                    totals[event] += statistics.median(values)
            line = {"frame": frame, "method": method, "decoded_bytes": byte_count,
                    "instructions_per_byte": totals["instructions"] / byte_count,
                    "cycles_per_byte": totals["cycles"] / byte_count,
                    "ipc": totals["instructions"] / totals["cycles"],
                    "branches_per_byte": totals["branches"] / byte_count,
                    "branch_misses_per_kib": 1024 * totals["branch-misses"] / byte_count,
                    "l1d_misses_per_kib": 1024 * totals["L1-dcache-load-misses"] / byte_count,
                    "llc_misses_per_kib": 1024 * totals["LLC-load-misses"] / byte_count}
            result.append(line)
    return result


# Innermost-first inline chain -> one exclusive category. Line ranges are for
# crates/deflate-core/src/block.rs and decode_table.rs at the recorded hashes.
BLOCK_SHA256 = "f75872205f5550962d60688e6fb5c6071684752d17e5d46387aab31ffec7c418"
BLOCK_RANGES = [(169, 213, "batch setup / output resize"), (214, 230, "batch setup / output resize"),
                (231, 243, "bit refill"), (244, 247, "literal/length dispatch"),
                (248, 262, "literal path"), (263, 265, "end of block"),
                (266, 287, "length/distance decode"), (288, 336, "match copy"),
                (337, 442, "slow path (slice token / tail)")]


def category(chain):
    for function, location in chain:
        file, _, line = location.rpartition(":")
        line = int(line) if line.isdigit() else 0
        name = file.rsplit("/", 1)[-1]
        if "panic" in function or "slice_index" in function or "_fail" in function:
            return "panic/bounds failure path"
        if name == "decode_table.rs":
            # Inline records may carry an outer function name; use lines.
            if 39 <= line <= 42:
                return "match-value extraction"
            if 63 <= line <= 72 or 129 <= line <= 132:
                return "table lookup"
            return "decode_table other" if line else "decode_table (no line)"
        if name == "block.rs":
            for low, high, label in BLOCK_RANGES:
                if low <= line <= high:
                    return label
            return "block.rs other" if line else "block.rs (no line)"
        if name in ("bitstream.rs", "huffman.rs", "inflate.rs", "gzip.rs", "crc32.rs", "lz77.rs"):
            return f"{name.removesuffix('.rs')}"
    return "std/other (no core frame)"


def load_segments(binary):
    segments = []
    for line in out(["readelf", "-lW", binary]).splitlines():
        fields = line.split()
        if fields[:1] == ["LOAD"]:
            segments.append((int(fields[1], 16), int(fields[2], 16), int(fields[4], 16)))
    return segments


def record(args):
    data = args.out / "perf.data"
    binary = args.binary.resolve()
    if not args.existing:
        args.out.mkdir(parents=True, exist_ok=False)
        command = worker_call(binary, args.codec, "context-warm", args.frame, args.packet,
                              args.out / "decoded", args.minimum_ns, args.expected)
        subprocess.run(["taskset", "-c", args.cpu, "perf", "record", "-q", "-F", str(args.frequency),
                        "-e", args.event, "-o", str(data), "--", *map(str, command)],
                       check=True, stdout=subprocess.DEVNULL)
    script = out(["perf", "script", "-i", data, "--show-mmap-events", "-F", "ip,dso"])
    maps, counts, dso_counts = {}, collections.Counter(), collections.Counter()
    for line in script.splitlines():
        mmap = re.search(r"PERF_RECORD_MMAP2? \d+/\d+: \[(0x[0-9a-f]+)\((0x[0-9a-f]+)\) @ (0x[0-9a-f]+|0) .*?\]: [rwxps-]+ (\S+)", line)
        if mmap:
            maps.setdefault(mmap[4], []).append((int(mmap[1], 16), int(mmap[2], 16), int(mmap[3], 16)))
            continue
        sample = re.match(r"\s*([0-9a-f]+) \((.*)\)", line)
        if sample:
            ip, dso = int(sample[1], 16), sample[2]
            dso_counts[Path(dso).name] += 1
            if dso == str(binary):
                counts[ip] += 1
    total = sum(dso_counts.values())
    report = {"binary": str(binary), "binary_sha256": sha(binary), "event": args.event, "packet": str(args.packet),
              "packet_sha256": sha(args.packet), "frame": args.frame, "samples": total,
              "dso_pct": {k: round(100 * v / total, 2) for k, v in dso_counts.most_common()}}
    if args.codec == "core":
        segments = load_segments(binary)
        regions = maps.get(str(binary), [])
        vaddrs = collections.Counter()
        for ip, count in counts.items():
            for start, length, pgoff in regions:
                if start <= ip < start + length:
                    offset = ip - start + pgoff
                    for seg_offset, seg_vaddr, seg_size in segments:
                        if seg_offset <= offset < seg_offset + seg_size:
                            vaddrs[offset - seg_offset + seg_vaddr] += count
                    break
        addresses = sorted(vaddrs)
        resolved = out(["addr2line", "-i", "-f", "-C", "-a", "-e", binary, *[hex(a) for a in addresses]]).splitlines()
        chains, current = {}, None
        index = 0
        while index < len(resolved):
            line = resolved[index]
            if line.startswith("0x"):
                current = int(line, 16)
                chains[current] = []
                index += 1
                continue
            chains[current].append((line, resolved[index + 1]))
            index += 2
        categories = collections.Counter()
        for address, count in vaddrs.items():
            categories[category(chains.get(address, []))] += count
        binary_samples = sum(vaddrs.values())
        report["core_binary_samples"] = binary_samples
        report["exclusive_category_pct_of_binary"] = {k: round(100 * v / binary_samples, 2)
                                                       for k, v in categories.most_common()}
        report["block_rs_sha256_expected"] = BLOCK_SHA256
        report["top_pcs"] = [{"vaddr": hex(a), "samples": c, "chain": chains.get(a, [])}
                             for a, c in vaddrs.most_common(40)]
    else:
        symbols = out(["perf", "report", "-i", data, "--stdio", "--sort", "dso,sym", "-g", "none",
                       "--percent-limit", "1"]).splitlines()
        report["top_symbols"] = [s for s in symbols if s and not s.startswith("#")]
    (args.out / "record.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("top_pcs", "top_symbols")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    refs = commands.add_parser("references")
    refs.add_argument("--out", type=Path, required=True)
    refs.add_argument("--source-lock", type=Path, required=True)
    refs.add_argument("--codec", choices=list(RELEASES), action="append", required=True)
    stat = commands.add_parser("counters")
    stat.add_argument("--workers", type=Path, required=True)
    stat.add_argument("--measure-run", type=Path, required=True)
    stat.add_argument("--core", type=Path, required=True)
    stat.add_argument("--accel", type=Path, required=True)
    stat.add_argument("--extra", action="append", help="LABEL=BINARY additional core-protocol worker")
    stat.add_argument("--cpu", required=True)
    stat.add_argument("--out", type=Path, required=True)
    stat.add_argument("--minimum-ns", type=int, default=1_000_000_000)
    stat.add_argument("--repeats", type=int, default=3)
    rec = commands.add_parser("record")
    rec.add_argument("--binary", type=Path, required=True)
    rec.add_argument("--codec", required=True)
    rec.add_argument("--frame", choices=["raw", "gzip"], required=True)
    rec.add_argument("--packet", type=Path, required=True)
    rec.add_argument("--expected", type=int, required=True)
    rec.add_argument("--cpu", required=True)
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument("--frequency", type=int, default=4999)
    rec.add_argument("--minimum-ns", type=int, default=4_000_000_000)
    rec.add_argument("--existing", action="store_true", help="re-attribute an existing perf.data")
    rec.add_argument("--event", default="cycles:u", help="sampled event, e.g. br_misp_retired.all_branches:upp")
    args = parser.parse_args()
    {"references": references, "counters": counters, "record": record}[args.command](args)


if __name__ == "__main__":
    main()
