#!/usr/bin/env bash
#
# Combine coverage data per tier and report each one, plus the total.
#
# Usage: coverage-summary.sh NAME=DIR [NAME=DIR ...]
#
# Writes three things, all under combined/, and prints the short one:
#   combined/summary.md   per-file tables, one per tier -- the job summary
#   combined/comment.md   one line per tier -- the PR comment
#   combined/<name>       the combined data file for each tier, and total
# htmlcov/ is written from the total. Nothing here is CI-specific, so the
# same report can be produced locally.
set -euo pipefail

mkdir -p combined
summary=combined/summary.md
comment=combined/comment.md
: > "$summary"
{
    printf '### Coverage\n\n'
    printf '| tier | coverage |\n| --- | --- |\n'
} > "$comment"

# `coverage combine` discovers inputs by the name of the data file it
# writes, so --data-file=combined/unit would look for `combined/unit.*` and
# find nothing. Hence combine then rename, into a directory the next pass
# will not read back in.
report() {
    local name=$1
    shift
    if ! coverage combine --keep "$@" >/dev/null 2>&1; then
        printf '### %s coverage\n\nNo data.\n\n' "$name" >> "$summary"
        printf '| %s | no data |\n' "$name" >> "$comment"
        return 1
    fi
    mv .coverage "combined/$name"
    {
        printf '### %s coverage\n\n' "$name"
        coverage report --data-file="combined/$name" --format=markdown
        printf '\n'
    } >> "$summary"
    printf '| %s | %s%% |\n' \
        "$name" "$(coverage report --data-file="combined/$name" --format=total)" >> "$comment"
}

dirs=()
for tier in "$@"; do
    report "${tier%%=*}" "${tier#*=}" || true
    dirs+=("${tier#*=}")
done

if report total "${dirs[@]}"; then
    coverage html --data-file=combined/total
fi

cat "$comment"
