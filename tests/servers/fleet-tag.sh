#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

paths=(servers/Dockerfile servers/docker-compose.yml)

# A `COPY --from=` source is a path inside that build stage, not in this
# tree; a leading `--chown=`/`--chmod=` is a flag, not a source.
while IFS= read -r path; do
    paths+=("$path")
done < <(
    awk '$1 == "COPY" {
             for (i = 2; i <= NF; i++) if ($i ~ /^--from=/) next
             for (i = 2; i < NF; i++) if ($i !~ /^--/) print $i
         }' servers/Dockerfile | sed 's:/*$::' | sort -u
)

# A fresh directory, not a mktemp file: git rejects an existing empty file as
# a truncated index.
index_dir=$(mktemp -d)
trap 'rm -rf "$index_dir"' EXIT
export GIT_INDEX_FILE="$index_dir/index"

git add --all -- "${paths[@]}"
tree=$(git write-tree)

revs=$(git rev-parse "${paths[@]/#/$tree:./}")
printf '%s\n' "$revs" | git hash-object --stdin
