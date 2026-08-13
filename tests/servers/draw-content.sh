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
set -e

export DISPLAY="${DISPLAY:-:0}"
READY_FILE="${DRAW_CONTENT_READY_FILE:-/tmp/draw-content-ready}"

for _ in $(seq 1 30); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

xlogo -geometry 200x200+50+50 &
XLOGO_PID=$!

for _ in $(seq 1 30); do
    xwininfo -name xlogo >/dev/null 2>&1 && break
    sleep 0.2
done

touch "$READY_FILE"

wait "$XLOGO_PID"
