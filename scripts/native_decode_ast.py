#!/usr/bin/env python3
"""Inspect pinned native decoder translation units using their recorded Clang flags.

Writes raw Clang JSON ASTs and a compact function/call inventory. Does not rebuild
or modify reference libraries. AST operation counts are not runtime costs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

UNITS = {
    "zlib-ng": ["inflate.c", "inftrees.c", "functable.c", "arch/arm/chunkset_neon.c", "arch/arm/crc32_armv8.c"],
    "libdeflate": ["lib/deflate_decompress.c", "lib/gzip_decompress.c", "lib/crc32.c"],
}
NAMES = re.compile(r"^(?:(?:libdeflate_|zng_)?(?:inflate|deflate_decompress|gzip_decompress|crc32)|build_.*decode_table|chunk|loadchunk|storechunk|arch_select_crc32_func|dispatch_decomp|init_functable)")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(node):
    yield node
    for child in node.get("inner", []):
        yield from walk(child)


def inventory(tree):
    result = []
    for node in walk(tree):
        if node.get("kind") != "FunctionDecl" or not NAMES.match(node.get("name", "")):
            continue
        body = next((n for n in node.get("inner", []) if n.get("kind") == "CompoundStmt"), None)
        if body is None:
            continue
        kinds = Counter()
        calls = Counter()
        indirect = 0
        references = set()
        for item in walk(body):
            kind = item.get("kind")
            kinds[kind] += 1
            if kind == "DeclRefExpr" and item.get("referencedDecl", {}).get("kind") == "FunctionDecl":
                references.add(item["referencedDecl"]["name"])
            if kind == "CallExpr":
                callee = item.get("inner", [])[:1]
                refs = [n["referencedDecl"]["name"] for c in callee for n in walk(c)
                        if n.get("kind") == "DeclRefExpr" and n.get("referencedDecl", {}).get("kind") == "FunctionDecl"]
                if refs:
                    calls.update(refs)
                else:
                    indirect += 1
        result.append({"name": node["name"], "type": node.get("type"),
                       "location": node.get("loc"), "range": node.get("range"),
                       "direct_call_sites": dict(sorted(calls.items())), "indirect_call_sites": indirect,
                       "function_references": sorted(references),
                       "syntax_counts": {k: kinds[k] for k in ["IfStmt", "SwitchStmt", "ForStmt", "WhileStmt", "DoStmt", "GotoStmt", "ArraySubscriptExpr", "CallExpr"]}})
    return result


def ast_command(command):
    args = shlex.split(command)
    result = [args[0]]
    index = 1
    while index < len(args):
        value = args[index]
        if value in ["-o", "-MF", "-MT", "-MQ"]:
            index += 2
            continue
        if value not in ["-c", "-MD", "-MMD", "-MP"]:
            result.append(value)
        index += 1
    return result + ["-fsyntax-only", "-Xclang", "-ast-dump=json"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    units = []
    for codec, files in UNITS.items():
        root = args.references.resolve() / codec
        receipt = json.loads((root / "build-receipt.json").read_text())
        assert sha(root / "source.tar.gz") == receipt["archive_sha256"], "source archive changed"
        assert sha(root / "compile-commands.json") == receipt["compile_commands_sha256"], "build commands changed"
        for path, digest in receipt["libraries"].items():
            assert sha(root / path) == digest, "reference binary changed"
        commands = json.loads((root / "compile-commands.json").read_text())
        for relative in files:
            source = root / "source" / relative
            candidates = [c for c in commands if c["file"] == str(source) and c["command"]]
            # The benchmark links the shared library, not the static build.
            selected = next((c for c in candidates if "_shared.dir" in c.get("output", "")), candidates[0])
            command = ast_command(selected["command"])
            name = codec + "-" + relative.replace("/", "_")
            ast = args.out / (name + ".ast.json")
            with ast.open("w") as output, (args.out / (name + ".stderr")).open("w") as error:
                subprocess.run(command, cwd=selected["directory"], stdout=output, stderr=error, check=True)
            functions = inventory(json.loads(ast.read_text()))
            units.append({"codec": codec, "release": receipt["release"], "source": relative,
                          "source_sha256": sha(source), "archive_sha256": receipt["archive_sha256"],
                          "compile_command": selected, "ast_command": command,
                          "ast_path": str(ast), "ast_sha256": sha(ast), "functions": functions})
            print(codec, relative, len(functions), "selected definitions", flush=True)
    report = {"compiler": subprocess.check_output(["clang", "--version"], text=True),
              "note": "Preprocessed build-specific AST; syntax counts are not runtime frequencies or costs.",
              "units": units}
    (args.out / "inventory.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
