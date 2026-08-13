#!/bin/sh
# Start a virtual X display (Xvfb) with x11vnc serving it, no authentication.
# Draw a trivial X client on it so captures aren't pure black.
set -e

Xvfb :0 -screen 0 1024x768x24 &
XVFB_PID=$!
trap 'kill -TERM "$XVFB_PID" 2>/dev/null; exit 0' TERM INT

export DISPLAY=:0
for _ in $(seq 1 30); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

xlogo -geometry 200x200+50+50 &

exec x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet
