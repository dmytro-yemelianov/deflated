#!/bin/sh
set -u

log=$(mktemp "${TMPDIR:-/tmp}/axioms.XXXXXX") || exit 1
trap 'rm -f "$log"' EXIT HUP INT TERM

if lake env lean spec/scripts/axioms.lean >"$log" 2>&1; then
    cat "$log"
else
    status=$?
    cat "$log" >&2
    echo "axiom checker failed with status $status" >&2
    exit "$status"
fi

if grep -qE 'sorryAx|ofReduceBool' "$log"; then
    echo "a headline theorem depends on sorryAx or ofReduceBool" >&2
    exit 1
fi
