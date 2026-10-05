#!/usr/bin/env bash
# Where decode time goes, per deflate-core function (spec §16: measure, then
# optimize). macOS only: needs samply (`cargo install samply`) and atos.
#
# Builds the perf example with line tables, samples it decoding one input in
# a loop, and writes inclusive per-function shares to target/reports/, or
# with --record to the baseline scripts/reports/profile.json (and regenerates
# the tables in docs/perf-report.md). Run scripts/perf_report.sh first; it
# makes the corpus.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v samply >/dev/null || { echo "needs samply: cargo install samply"; exit 1; }
corpus=target/perf-corpus
test -d "$corpus" || { echo "no $corpus: run scripts/perf_report.sh first"; exit 1; }
tdir=target/profiling
baseline=scripts/reports/profile.json
if [ "${1:-}" = "--record" ]; then out=$baseline; else out=target/reports/profile.json; fi
mkdir -p "$(dirname "$out")"
secs=${PERF_SECS:-4}

CARGO_PROFILE_RELEASE_DEBUG=line-tables-only CARGO_TARGET_DIR=$tdir \
  cargo build -q --release -p deflate-core --example perf
bin=$tdir/release/examples/perf
dsymutil "$bin"

inputs="text.dyn.deflate zeros.fixed.deflate repetitive.dyn.deflate text.stored.deflate"
{
  echo "{"
  printf '  "tool": "%s",\n  "seconds_per_input": %s,\n  "profiles": {\n' "$(samply --version)" "$secs"
  first=1
  for f in $inputs; do
    PERF_ONLY=$f PERF_SECS=$secs samply record --save-only --unstable-presymbolicate \
      -o "$tdir/$f.json.gz" -- "$bin" "$corpus" >/dev/null 2>&1
    [ $first -eq 1 ] || printf ',\n'
    first=0
    printf '    "%s": %s' "$f" "$(python3 scripts/profile_attrib.py "$tdir/$f.json.gz" "$bin")"
  done
  printf '\n  }\n}\n'
} > "$out"
cat "$out"
[ "$out" != "$baseline" ] || python3 scripts/render_perf_tables.py
