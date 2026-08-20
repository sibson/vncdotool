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

# `docker compose restart` reuses the container filesystem, and a lock left
# by an Xvnc that did not exit cleanly makes the next start die with
# "Server is already active for display 0".
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p /root/.vnc
    printf '%s' "$VNC_PASSWORD" | vncpasswd -f > /root/.vnc/passwd
    chmod 600 /root/.vnc/passwd
    # Xvnc counts every connection closed before a successful authentication
    # towards BlacklistThreshold, and a successful authentication clears the
    # host's blackmark. The readiness probe never authenticates (see the
    # HEALTHCHECK in Dockerfile), so a generous threshold avoids blacklisting
    # the harness itself while still capping real password guessing.
    set -- -SecurityTypes VncAuth -PasswordFile /root/.vnc/passwd -BlacklistThreshold=50
else
    set -- -SecurityTypes None
fi

Xvnc :0 \
    "$@" \
    -rfbport 5900 \
    -geometry "${VNC_GEOMETRY:-1024x768}" \
    -depth 24 \
    -AlwaysShared \
    -localhost=0 &
XVNC_PID=$!

DISPLAY=:0 python3 -m tests.goldens.scene_player &

wait "$XVNC_PID"
