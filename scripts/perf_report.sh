#!/usr/bin/env bash
# Reproducible decode-throughput baseline (spec §16: "baseline → optimized
# candidate → … → size/performance measurement").
#
# Times deflate-core against miniz_oxide in-process on a seeded corpus, best
# of REPS runs each. Absolute MB/s depend on the machine; the slowdown ratio
# is what an optimization moves.
#
# By default the run goes to target/reports/perf.json and is printed next to
# the committed baseline. With --record it replaces the baseline,
# scripts/reports/perf.json, and regenerates the tables in
# docs/perf-report.md, which quotes only that file.
set -euo pipefail
cd "$(dirname "$0")/.."
baseline=scripts/reports/perf.json
cbaseline=scripts/reports/compress.json
if [ "${1:-}" = "--record" ]; then out=$baseline; cout=$cbaseline; else out=target/reports/perf.json; cout=target/reports/compress.json; fi
mkdir -p "$(dirname "$out")"
corpus=target/perf-corpus
reps=${REPS:-15}

python3 scripts/perf_corpus.py "$corpus"
cargo build -q --release -p deflate-core --example perf
results=$(./target/release/examples/perf "$corpus" "$reps")
# Encoder: fewer reps, each run compresses 8 MiB.
creps=${CREPS:-5}
cresults=$(./target/release/examples/perf compress "$corpus" "$creps")

cpu=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || awk -F': ' '/model name/ {print $2; exit}' /proc/cpuinfo)
miniz=$(cargo tree -p deflate-core -e dev --depth 1 | awk '/miniz_oxide/ {print $NF}')
{
  echo "{"
  printf '  "host": "%s",\n  "cpu": "%s",\n  "rustc": "%s",\n  "uname": "%s",\n' \
    "$(rustc -vV | awk '/host:/ {print $2}')" "$cpu" "$(rustc --version)" "$(uname -srm)"
  printf '  "profile": "release",\n  "reference": "miniz_oxide %s",\n  "reps": %s,\n' "$miniz" "$reps"
  printf '  "results": '
  echo "$results" | sed '1!s/^/  /'
  echo "}"
} > "$out"
{
  echo "{"
  printf '  "host": "%s",\n  "cpu": "%s",\n  "rustc": "%s",\n  "uname": "%s",\n' \
    "$(rustc -vV | awk '/host:/ {print $2}')" "$cpu" "$(rustc --version)" "$(uname -srm)"
  printf '  "profile": "release",\n  "reference": "miniz_oxide %s levels 1 and 6",\n  "reps": %s,\n' "$miniz" "$creps"
  printf '  "results": '
  echo "$cresults" | sed '1!s/^/  /'
  echo "}"
} > "$cout"
if [ "$out" = "$baseline" ]; then
  python3 scripts/render_perf_tables.py
  cat "$out"
else
  python3 - "$baseline" "$out" <<'PY'
import json, sys
base = {r["input"]: r for r in json.load(open(sys.argv[1]))["results"]}
print(f"{'input':28} {'baseline':>9} {'now':>9}  slowdown vs miniz_oxide (lower is better)")
for r in json.load(open(sys.argv[2]))["results"]:
    b = base.get(r["input"], {}).get("slowdown")
    print(f"{r['input']:28} {b if b is not None else '-':>9} {r['slowdown']:>9}")
PY
fi
python3 - "$cbaseline" "$cout" <<'PY'
import json, sys
try:
    base = {r["input"]: r for r in json.load(open(sys.argv[1]))["results"]}
except FileNotFoundError:
    base = {}
print(f"{'compress input':28} {'ratio':>8} {'MB/s':>8}  (baseline ratio, MB/s)")
for r in json.load(open(sys.argv[2]))["results"]:
    b = base.get(r["input"], {})
    print(f"{r['input']:28} {r['deflate_core_ratio']:>8} {r['deflate_core_mb_s']:>8}  ({b.get('deflate_core_ratio', '-')}, {b.get('deflate_core_mb_s', '-')})")
PY
