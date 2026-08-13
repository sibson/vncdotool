#!/bin/bash
# Collect Screen Sharing / Remote Management logs and display state into a
# directory, so CI can upload it as an artifact.
#
# Never fails: a run that has already gone wrong must not lose the evidence
# to a second error.
#
# Usage: bash tests/servers/screen-sharing/collect-diagnostics.sh [destination]
set -u

DESTINATION="${1:-diagnostics}"
PORT="${VNCDOTOOL_OS_SERVER_PORT:-5900}"

mkdir -p "$DESTINATION"

log show --last 10m --predicate \
    'process CONTAINS "ARDAgent" OR process CONTAINS "screensharingd" OR process CONTAINS "AppleVNCServer" OR process CONTAINS "loginwindow" OR process CONTAINS "WindowServer"' \
    >"$DESTINATION/system.log" 2>&1

sudo lsof -iTCP:"$PORT" -sTCP:LISTEN -P >"$DESTINATION/port$PORT.log" 2>&1
who >"$DESTINATION/who.log" 2>&1
stat -f "console owner: %Su" /dev/console >"$DESTINATION/console.log" 2>&1
pmset -g >"$DESTINATION/pmset.log" 2>&1
system_profiler SPDisplaysDataType >"$DESTINATION/displays.log" 2>&1

echo "collected Screen Sharing diagnostics into $DESTINATION"
ls -l "$DESTINATION"
exit 0
