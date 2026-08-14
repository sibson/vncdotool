#!/bin/sh
# Put a trivial X client on the display so captures aren't pure black.
# Without one the framebuffer is flat, and a flat capture is
# indistinguishable from "we never received an update" --
# tests/functional/test_servers.py asserts captures aren't flat.
#
# This script does not decide readiness. Whether the content actually
# arrived is settled by `tests/functional/wait_for_servers.py docker`,
# which connects and captures until the screen holds what the server is
# supposed to render. An in-container marker file used to stand in for
# that and was worse than nothing: it waited with
# `cmd >/dev/null 2>&1 && break`, which cannot tell "not ready yet" from
# "that program isn't installed", and then created the marker whether or
# not either wait had succeeded. x11-utils was missing from the tigervnc
# image, so both waits ran to exhaustion and the marker was really a fixed
# 21s sleep that reported ready against a blank screen.
#
# The waits that remain are still worth getting right, because xlogo needs
# a display to draw on, so failures here stay loud: a missing tool is a
# hard error, and a wait that runs out is a hard error.
set -e

export DISPLAY="${DISPLAY:-:0}"

require() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "draw-content: $1 is not installed in this image" >&2
        exit 1
    }
}

# wait_for <attempts> <delay> <command...>
wait_for() {
    attempts=$1
    delay=$2
    shift 2
    while [ "$attempts" -gt 0 ]; do
        if "$@" >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep "$delay"
    done
    echo "draw-content: gave up waiting for: $*" >&2
    return 1
}

require xdpyinfo
require xwininfo
require xlogo

wait_for 30 0.5 xdpyinfo

xlogo -geometry 200x200+50+50 &
XLOGO_PID=$!

wait_for 30 0.2 xwininfo -name xlogo

wait "$XLOGO_PID"
