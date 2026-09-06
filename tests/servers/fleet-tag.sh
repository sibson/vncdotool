#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# A `COPY --from=` source is a path inside that build stage, not in this
# tree; a leading `--chown=`/`--chmod=` is a flag, not a source.
paths=(servers)
while IFS= read -r path; do
    paths+=("$path")
done < <(
    awk '$1 == "COPY" {
             for (i = 2; i <= NF; i++) if ($i ~ /^--from=/) next
             for (i = 2; i < NF; i++) if ($i !~ /^--/) print $i
         }' servers/Dockerfile | sed 's:/*$::' | sort -u
)

revs=$(git rev-parse "${paths[@]/#/HEAD:./}")
printf '%s\n' "$revs" | git hash-object --stdin
