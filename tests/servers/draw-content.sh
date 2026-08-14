#!/bin/sh
# Wait for the X display to accept connections, draw a trivial X client on
# it, and only then signal readiness via a marker file. Without a client
# the framebuffer is pure black, and a black capture is indistinguishable
# from "we never received an update" -- tests/functional/test_servers.py
# asserts captures aren't flat.
#
# The marker file matters because "the RFB port accepts connections" is
# not the same thing as "there is content on screen": Xvnc in particular
# starts accepting connections the instant it launches, well before this
# script's backgrounded xlogo has mapped a window, so a probe of the port
# alone lets the image report healthy while the framebuffer is still
# flat. The image HEALTHCHECK checks for this file's existence in
# addition to the port so `docker compose up --wait` only reports the
# container ready once there is actually something to capture.
#
# Every failure here must stay loud. This script is the whole content half
# of the readiness gate, so anything it lets through silently becomes a
# green test run against a blank screen. It previously waited with
# `cmd >/dev/null 2>&1 && break`, which cannot tell "not ready yet" from
# "that program isn't installed" -- and x11-utils wasn't in the tigervnc
# image, so both waits ran to exhaustion and the marker was really a fixed
# 21s sleep. Hence: missing tools are a hard error, and a wait that runs
# out is a hard error rather than a fall-through to touching the marker.
set -e

export DISPLAY="${DISPLAY:-:0}"
READY_FILE="${DRAW_CONTENT_READY_FILE:-/tmp/draw-content-ready}"

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

touch "$READY_FILE"

wait "$XLOGO_PID"
