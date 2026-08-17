#!/usr/bin/env bash
#
# Post BODY_FILE as a PR comment, editing the previous one rather than
# adding another on every push.
#
# Usage: pr-sticky-comment.sh MARKER PR_NUMBER BODY_FILE
#
# Needs GH_TOKEN with pull-requests: write. A PR from a fork gets a
# read-only token, so this cannot post there; call it with
# continue-on-error and let the job summary carry the report instead.
set -euo pipefail

marker=$1
pr=$2
body_file=$3
repo=${GITHUB_REPOSITORY:?}

body="$(cat "$body_file")
<!-- $marker -->"

existing=$(gh api "repos/$repo/issues/$pr/comments" --paginate \
    --jq "[.[] | select(.body | contains(\"<!-- $marker -->\")) | .id] | first // empty")

if [ -n "$existing" ]; then
    gh api --method PATCH "repos/$repo/issues/comments/$existing" -f body="$body" --jq .html_url
else
    gh api --method POST "repos/$repo/issues/$pr/comments" -f body="$body" --jq .html_url
fi
