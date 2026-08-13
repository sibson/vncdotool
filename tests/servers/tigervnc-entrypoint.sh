#!/bin/sh
# Start a TigerVNC (Xvnc) server, with or without authentication.
#
# VNC_PASSWORD unset or empty -> SecurityTypes None.
# VNC_PASSWORD set            -> classic VNC password auth, with the
#                                password written at start-up by vncpasswd
#                                so it is never baked into the image.
# That is the only difference between the two TigerVNC services in
# docker-compose.yml, so they share this entrypoint and the image.
set -e

trap 'kill -TERM "$XVNC_PID" 2>/dev/null; exit 0' TERM INT

if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p /root/.vnc
    printf '%s' "$VNC_PASSWORD" | vncpasswd -f > /root/.vnc/passwd
    chmod 600 /root/.vnc/passwd
    set -- -SecurityTypes VncAuth -PasswordFile /root/.vnc/passwd
else
    set -- -SecurityTypes None
fi

Xvnc :0 \
    "$@" \
    -rfbport 5900 \
    -geometry 1024x768 \
    -depth 24 \
    -AlwaysShared \
    -localhost=0 &
XVNC_PID=$!

DISPLAY=:0 /draw-content.sh &

wait "$XVNC_PID"
