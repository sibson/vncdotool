#!/usr/bin/env bash
#
# Combine coverage data per tier and report each one, plus the total.
#
# Usage: coverage-summary.sh NAME=DIR [NAME=DIR ...]
#
# Writes combined/summary.md -- a table of one number per tier, with the
# per-file tables folded away underneath it -- and prints it. htmlcov/ is
# written from the total, combined/<name> holds each tier's combined data,
# and combined/xml/<name>.xml is the same tier as Cobertura. Nothing here
# is CI-specific, so the same report can be produced locally.
set -euo pipefail

mkdir -p combined/xml
summary=combined/summary.md
detail=combined/detail.md
totals=combined/totals.md
: > "$detail"
printf '## Coverage\n\n| tier | coverage |\n| --- | --- |\n' > "$totals"

# `coverage combine` discovers inputs by the name of the data file it
# writes, so --data-file=combined/unit would look for `combined/unit.*` and
# find nothing. Hence combine then rename, into a directory the next pass
# will not read back in.
report() {
    local name=$1
    shift
    if ! coverage combine --keep "$@" >/dev/null 2>&1; then
        printf '| %s | no data |\n' "$name" >> "$totals"
        return 1
    fi
    mv .coverage "combined/$name"
    printf '| %s | %s%% |\n' \
        "$name" "$(coverage report --data-file="combined/$name" --format=total)" >> "$totals"
    {
        printf '#### %s\n\n' "$name"
        coverage report --data-file="combined/$name" --format=markdown
        printf '\n'
    } >> "$detail"
    # Into a subdirectory: `combined/$name.xml` is itself a `combined/$name.*`
    # match, so the next report of that tier tries to combine the XML as if it
    # were a data file.
    coverage xml --data-file="combined/$name" -o "combined/xml/$name.xml"
}

dirs=()
for tier in "$@"; do
    report "${tier%%=*}" "${tier#*=}" || true
    dirs+=("${tier#*=}")
done

if report total "${dirs[@]}"; then
    coverage html --data-file=combined/total
fi

{
    cat "$totals"
    printf '\n<details><summary>Per-file detail</summary>\n\n'
    cat "$detail"
    printf '</details>\n'
} > "$summary"
cat "$summary"
