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
    # Xvnc counts every connection closed before a successful authentication
    # towards BlacklistThreshold, and a successful authentication clears the
    # host's blackmark. The readiness probe no longer connects at all (see the
    # HEALTHCHECK in Dockerfile), but the harness still leaves some: about
    # seven port_open() reachability probes per full run plus the one
    # deliberate wrong password in tests/functional/test_cli.py. A full run
    # interleaves enough successful authentications to stay under the default
    # of 5, but running test_cli.py alone, repeatedly, chains them without one.
    # 50 absorbs several such runs while still capping real password guessing.
    set -- -SecurityTypes VncAuth -PasswordFile /root/.vnc/passwd -BlacklistThreshold=50
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
