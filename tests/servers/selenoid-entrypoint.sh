#!/bin/sh
# Selenoid bridging its own WebSocket endpoint to a local VNC server.
#
# `-disable-docker` runs the browser as a process rather than a container,
# and Selenoid then bridges to 127.0.0.1:5900, a port it hardcodes -- which
# is why Xvnc has to sit there.
set -e

trap 'kill -TERM "$XVNC_PID" 2>/dev/null; exit 0' TERM INT

rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

Xvnc :0 \
    -SecurityTypes None \
    -rfbport 5900 \
    -geometry "${VNC_GEOMETRY:-1024x768}" \
    -depth 24 \
    -AlwaysShared \
    -localhost=0 &
XVNC_PID=$!

DISPLAY=:0 python3 -m tests.goldens.scene_player &

selenoid \
    -listen :4444 \
    -conf /etc/selenoid/browsers.json \
    -disable-docker \
    -limit 5 &

wait "$XVNC_PID"
