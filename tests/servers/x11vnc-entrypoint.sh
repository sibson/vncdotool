#!/bin/sh
# Start a virtual X display (Xvfb) with x11vnc serving it, no authentication.
set -e

Xvfb :0 -screen 0 1024x768x24 &
XVFB_PID=$!
trap 'kill -TERM "$XVFB_PID" 2>/dev/null; exit 0' TERM INT

DISPLAY=:0 /draw-content.sh &

exec x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet
