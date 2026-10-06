#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/axiom-gate-test.XXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

cat >"$tmp/lake" <<'EOF'
#!/bin/sh
printf '%s\n' "${AXIOM_OUTPUT:-axioms: [propext]}"
exit "${AXIOM_STATUS:-0}"
EOF
chmod +x "$tmp/lake"

run_gate() {
    status=$1
    output=$2
    (cd "$root" && PATH="$tmp:$PATH" AXIOM_STATUS="$status" AXIOM_OUTPUT="$output" sh scripts/axiom_gate.sh)
}

if run_gate 23 'axioms: [propext]' >"$tmp/out" 2>&1; then
    echo "axiom gate accepted checker exit 23" >&2
    exit 1
else
    status=$?
    if [ "$status" -ne 23 ]; then
        echo "axiom gate returned $status for checker exit 23" >&2
        exit 1
    fi
fi
if run_gate 0 'axioms: [sorryAx]' >"$tmp/out" 2>&1; then
    echo "axiom gate accepted sorryAx" >&2
    exit 1
fi
if run_gate 0 'axioms: [ofReduceBool]' >"$tmp/out" 2>&1; then
    echo "axiom gate accepted ofReduceBool" >&2
    exit 1
fi
run_gate 0 'axioms: [propext, Quot.sound]' >/dev/null
echo "axiom gate regression checks passed"
