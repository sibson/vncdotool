#!/bin/sh
# Wait for the X display to accept connections, then draw a trivial X
# client on it. Without a client the framebuffer is pure black, and a
# black capture is indistinguishable from "we never received an update"
# -- tests/functional/test_servers.py asserts captures aren't flat.
set -e

export DISPLAY="${DISPLAY:-:0}"

for _ in $(seq 1 30); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

exec xlogo -geometry 200x200+50+50
