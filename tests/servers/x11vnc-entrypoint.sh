#!/bin/sh
# Start a virtual X display (Xvfb) with x11vnc serving it, no authentication.
set -e

Xvfb :0 -screen 0 1024x768x24 &
XVFB_PID=$!
trap 'kill -TERM "$XVFB_PID" 2>/dev/null; exit 0' TERM INT

DISPLAY=:0 /draw-content.sh &

# X-side event sink: confirms an event arrived as a real X event, not just
# that the client put it on the wire. Prefixed so it greps cleanly out of
# `docker compose logs x11vnc`.
(
    for _ in $(seq 1 30); do
        DISPLAY=:0 xdpyinfo >/dev/null 2>&1 && break
        sleep 0.5
    done
    DISPLAY=:0 xev -root
) 2>&1 | sed -u 's/^/xev: /' &

exec x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet
