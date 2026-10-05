#!/usr/bin/env python3
"""Regenerate the tables in docs/perf-report.md from the committed JSON.

The tables sit between <!-- perf:NAME --> and <!-- /perf:NAME --> markers and
are never edited by hand, so a new baseline cannot leave a stale table behind.
"""
import json
import re

DOC = "docs/perf-report.md"


def throughput(perf):
    rows = [
        "| Input | Compressed bytes | deflate-core MB/s | miniz_oxide MB/s | Slowdown |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in perf["results"]:
        rows.append(
            f"| `{r['input']}` | {r['compressed_bytes']} | {r['deflate_core_mb_s']} "
            f"| {r['miniz_oxide_mb_s']} | {r['slowdown']}× |"
        )
    return "\n".join(rows)


def profile(prof):
    out = []
    for name, d in prof["profiles"].items():
        out += [f"`{name}` ({d['samples']} samples)", "", "| Function | Inclusive % |", "| --- | ---: |"]
        out += [f"| `{k}` | {v} |" for k, v in d["inclusive_pct"].items()]
        out += [f"| {k} | {v} |" for k, v in d["outside_core_pct"].items()]
        out.append("")
    return "\n".join(out).rstrip()


def main():
    tables = {
        "throughput": throughput(json.load(open("scripts/reports/perf.json"))),
        "profile": profile(json.load(open("scripts/reports/profile.json"))),
    }
    doc = open(DOC).read()
    for name, body in tables.items():
        pat = re.compile(rf"(<!-- perf:{name} -->\n).*?(\n<!-- /perf:{name} -->)", re.S)
        doc, n = pat.subn(lambda m: m.group(1) + body + m.group(2), doc)
        if n != 1:
            raise SystemExit(f"{DOC}: marker perf:{name} missing")
    open(DOC, "w").write(doc)


if __name__ == "__main__":
    main()
