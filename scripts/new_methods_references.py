#!/usr/bin/env python3
"""Acquire pinned releases and build isolated native reference libraries.

Source/build receipts are not a measurement lock: adapter settings and roundtrip
evidence must be added before any screening. No system package is installed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RELEASES = {
    "zlib": ("madler/zlib", "v1.3.2", ".", ["-DZLIB_BUILD_TESTING=OFF"]),
    "zlib-ng": ("zlib-ng/zlib-ng", "2.3.3", ".", ["-DZLIB_COMPAT=OFF", "-DZLIB_ENABLE_TESTS=OFF"]),
    "libdeflate": ("ebiggers/libdeflate", "v1.26", ".", ["-DLIBDEFLATE_BUILD_GZIP=OFF", "-DLIBDEFLATE_BUILD_TESTS=OFF"]),
    "zstd": ("facebook/zstd", "v1.5.7", "build/cmake", ["-DZSTD_BUILD_PROGRAMS=OFF", "-DZSTD_BUILD_TESTS=OFF", "-DZSTD_BUILD_STATIC=OFF"]),
    "lz4": ("lz4/lz4", "v1.10.0", "build/cmake", ["-DLZ4_BUILD_CLI=OFF", "-DLZ4_BUILD_LEGACY_LZ4C=OFF"]),
    "brotli": ("google/brotli", "v1.2.0", ".", ["-DBROTLI_BUILD_TOOLS=OFF", "-DBROTLI_DISABLE_TESTS=ON"]),
    "lzma2": ("tukaani-project/xz", "v5.8.4", ".", ["-DBUILD_TESTING=OFF"]),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(name, out, locked=None):
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / "attempts.json"
    attempts = json.loads(ledger.read_text()) if ledger.exists() else []
    if len(attempts) >= 2:
        raise RuntimeError(f"{name}: two setup attempts exhausted")
    if (directory / "build-receipt.json").exists():
        raise RuntimeError(f"{name}: existing successful build; refusing replacement")
    entry = {"attempt": len(attempts) + 1, "status": "started"}
    attempts.append(entry)

    def save():
        ledger.write_text(json.dumps(attempts, indent=2) + "\n")

    save()
    repo, release, subdir, options = RELEASES[name]
    archive = directory / "source.tar.gz"
    source = directory / "source"
    url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{release}"
    try:
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                archive.write_bytes(response.read())
        archive_hash = digest(archive)
        if locked:
            if archive_hash != locked[name]["archive_sha256"]:
                raise RuntimeError("source hash differs from supplied lock")
        if not source.exists():
            with tarfile.open(archive) as bundle:
                # Extraction filter rejects absolute paths and traversal/special
                # entries. Our source archives have exactly one root directory.
                roots = {Path(member.name).parts[0] for member in bundle.getmembers()}
                if len(roots) != 1:
                    raise RuntimeError("unexpected archive roots")
                bundle.extractall(directory / "unpacked", filter="data")
            (directory / "unpacked" / roots.pop()).rename(source)
        compiler = subprocess.check_output(["clang", "--version"], text=True).strip()
        configure = ["cmake", "-S", str(source / subdir), "-B", str(directory / "build"),
                     "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON",
                     "-DCMAKE_C_COMPILER=/usr/bin/clang", "-DCMAKE_CXX_COMPILER=/usr/bin/clang++",
                     "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG", "-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG",
                     f"-DCMAKE_INSTALL_PREFIX={directory / 'install'}", *options]
        commands = [configure, ["cmake", "--build", str(directory / "build"), "--parallel", "4"],
                    ["cmake", "--install", str(directory / "build")]]
        env = os.environ.copy()
        removed = {k: env.pop(k) for k in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "CXX", "CMAKE_PREFIX_PATH") if k in env}
        for index, command in enumerate(commands):
            with (directory / f"attempt{entry['attempt']}-step{index}.log").open("w") as log:
                result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f"build step {index} failed ({result.returncode}); see recorded log")
        libraries = {str(p.relative_to(directory)): digest(p) for p in sorted((directory / "install/lib").glob("*.dylib")) if not p.is_symlink()}
        if not libraries:
            raise RuntimeError("no installed native shared library")
        compile_commands = subprocess.check_output(
            ["ninja", "-C", str(directory / "build"), "-t", "compdb"], text=True)
        (directory / "compile-commands.json").write_text(compile_commands)
        cache = (directory / "build/CMakeCache.txt").read_text()
        cache_flags = {line.split(":", 1)[0]: line.split("=", 1)[1]
                       for line in cache.splitlines() if not line.startswith(("#", "//"))
                       and ":" in line and "=" in line
                       and any(key in line.split(":", 1)[0] for key in
                               ("FLAGS", "BUILD_SHARED", "ZLIB_COMPAT", "ENABLE_TESTS", "BUILD_TESTS", "BUILD_TESTING"))}
        receipt = {"schema_version": 1, "codec": name, "release": release, "url": url,
                   "archive_sha256": archive_hash, "compiler": compiler, "host": platform.platform(),
                   "commands": commands, "removed_environment": removed, "libraries": libraries,
                   "compile_commands_sha256": digest(directory / "compile-commands.json"),
                   "cmake_cache_sha256": digest(directory / "build/CMakeCache.txt"),
                   "effective_cache_flags": cache_flags,
                   "status": "source/build sealed; adapter, settings and independent validation pending"}
        (directory / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        entry["status"] = "passed"
        entry["archive_sha256"] = archive_hash
        save()
        print(json.dumps({"codec": name, "release": release, "archive_sha256": archive_hash, "status": "built"}), flush=True)
        return receipt
    except Exception as error:
        entry.update(status="failed", reason=str(error))
        save()
        print(json.dumps({"codec": name, "status": "failed", "reason": str(error)}), flush=True)
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/references-v1")
    parser.add_argument("--codec", choices=list(RELEASES), action="append")
    parser.add_argument("--source-lock", type=Path, help="require previously published archive hashes")
    args = parser.parse_args()
    locked = json.loads(args.source_lock.read_text()) if args.source_lock else None
    failed = False
    for name in args.codec or RELEASES:
        failed |= build(name, args.out.resolve(), locked) is None
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
