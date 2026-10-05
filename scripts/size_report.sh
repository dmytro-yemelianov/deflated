#!/usr/bin/env bash
# Reproducible binary-size measurement (spec §15, §18.12).
#
# Records the whole executable size *and* its sections separately, because
# §15 says never to claim .text as the total. Everything measured here is
# written to scripts/reports/size.json; docs/size-report.md quotes only that
# file, and scripts/check_size_report.sh enforces it.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p scripts/reports
out=scripts/reports/size.json

host=$(rustc -vV | awk '/host:/ {print $2}')
rustc_v=$(rustc --version)
uname_s=$(uname -srm)

size_tool=$(command -v llvm-size || xcrun -f llvm-size 2>/dev/null || command -v size)

# Working memory: preserve committed baseline if present to avoid OS page-jitter,
# or measure once if missing or if --remeasure-rss is passed.
wm_json="/tmp/wm.json"
if [ "${1:-}" != "--remeasure-rss" ] && [ -f "$out" ] && python3 -c "import json, sys; sys.exit(0 if 'working_memory' in json.load(open('$out')) else 1)" 2>/dev/null; then
  python3 -c "import json; d = json.load(open('$out')); print(json.dumps(d['working_memory'], indent=4))" > "$wm_json"
else
  cargo build --profile min -p vdeflate >/dev/null
  big_input="/tmp/big.deflate"
  python3 -c "import zlib,sys; sys.stdout.buffer.write(zlib.compress(bytes(range(256))*4096, 9)[2:-4])" > "$big_input"
  comp_size=$(wc -c < "$big_input" | tr -d ' ')
  decomp_size=1048576
  limit_bytes=16777216

  mem_log="/tmp/vdeflate_mem.txt"
  /usr/bin/time -l ./target/min/vdeflate -d --limit "$limit_bytes" < "$big_input" > /dev/null 2> "$mem_log" || true
  peak_rss=$(awk '/maximum resident/ {print $1}' "$mem_log")
  rm -f "$big_input" "$mem_log"
  cat <<EOF > "$wm_json"
{
  "input_name": "big.deflate",
  "compressed_bytes": $comp_size,
  "decompressed_bytes": $decomp_size,
  "limit_bytes": $limit_bytes,
  "peak_rss_bytes": $peak_rss
}
EOF
fi

echo "{" > "$out"
printf '  "host": "%s",\n  "rustc": "%s",\n  "uname": "%s",\n  "size_tool": "%s",\n' \
  "$host" "$rustc_v" "$uname_s" "$size_tool" >> "$out"
printf '  "profiles": {\n' >> "$out"

first=1
for profile in release min; do
  cargo build --profile "$profile" -p vdeflate >/dev/null
  dir=$([ "$profile" = release ] && echo release || echo "$profile")
  bin="target/$dir/vdeflate"
  total=$(wc -c < "$bin" | tr -d ' ')
  # Section sizes, each named, never summed into a single headline number.
  sections=$("$size_tool" -A "$bin" 2>/dev/null \
    | awk 'NF>=2 && $2 ~ /^[0-9]+$/ && $1 != "Total" {printf "%s\"%s\": %s", (c++?", ":""), $1, $2}')
  [ $first -eq 1 ] || printf ',\n' >> "$out"
  first=0
  printf '    "%s": {\n      "total_bytes": %s,\n      "sections": { %s }\n    }' \
    "$profile" "$total" "$sections" >> "$out"
done
printf '\n  },\n' >> "$out"

printf '  "working_memory": ' >> "$out"
sed 's/^/  /' "$wm_json" | sed '1s/^ *//' >> "$out"
echo "}" >> "$out"
rm -f "$wm_json"

cat "$out"
