#!/usr/bin/env bash
#
# Combine coverage data per tier and report each one, plus the total.
#
# Usage: coverage-summary.sh NAME=DIR [NAME=DIR ...]
#
# Writes markdown to $GITHUB_STEP_SUMMARY, or to stdout when that is unset,
# so a CI report can be reproduced locally. Leaves the combined data in
# combined/ and writes htmlcov/ from the total.
set -euo pipefail

out=${GITHUB_STEP_SUMMARY:-/dev/stdout}
mkdir -p combined

# `coverage combine` discovers inputs by the name of the data file it
# writes, so --data-file=combined/unit would look for `combined/unit.*` and
# find nothing. Hence combine then rename, into a directory the next pass
# will not read back in.
report() {
    local name=$1
    shift
    if ! coverage combine --keep "$@" >/dev/null 2>&1; then
        printf '### %s coverage\n\nNo data.\n\n' "$name" >> "$out"
        return 1
    fi
    mv .coverage "combined/$name"
    {
        printf '### %s coverage\n\n' "$name"
        coverage report --data-file="combined/$name" --format=markdown
        printf '\n'
    } >> "$out"
}

dirs=()
for tier in "$@"; do
    report "${tier%%=*}" "${tier#*=}" || true
    dirs+=("${tier#*=}")
done

if report total "${dirs[@]}"; then
    coverage html --data-file=combined/total
fi
