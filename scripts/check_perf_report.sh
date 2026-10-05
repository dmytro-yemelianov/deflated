#!/usr/bin/env bash
# Every number in docs/perf-report.md must appear in scripts/reports/perf.json
# or scripts/reports/profile.json. Same rule as scripts/check_size_report.sh,
# extended to decimals, because throughput and profile shares are decimals.
set -euo pipefail
md=docs/perf-report.md
data=$(cat scripts/reports/perf.json scripts/reports/profile.json)
test -s "$md" || { echo "missing $md"; exit 1; }
missing=0
while read -r n; do
  grep -qF -- "$n" <<<"$data" || { echo "number in prose but not in data: $n"; missing=1; }
done < <(grep -oE '\b[0-9]+\.[0-9]+\b|\b[0-9]{3,}\b' "$md" | sort -u)
exit $missing
