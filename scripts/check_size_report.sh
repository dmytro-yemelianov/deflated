#!/usr/bin/env bash
# Every number in docs/size-report.md must appear in scripts/reports/size.json.
# The lesson of maked's "benchmark that lied": a number in prose that no longer
# matches the raw data is how a wrong measurement survives review.
set -euo pipefail
json=scripts/reports/size.json
md=docs/size-report.md
test -s "$json" || { echo "missing $json"; exit 1; }
test -s "$md" || { echo "missing $md"; exit 1; }
missing=0
while read -r n; do
  grep -q -- "$n" "$json" || { echo "number in prose but not in data: $n"; missing=1; }
done < <(grep -oE '\b[0-9][0-9,]{2,}\b' "$md" | tr -d ',' | sort -u)
exit $missing
