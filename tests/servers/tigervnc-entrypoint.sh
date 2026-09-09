#!/bin/sh
# Start a TigerVNC (Xvnc) server, with or without authentication.
#
# VNC_PASSWORD unset or empty -> SecurityTypes None.
# VNC_PASSWORD set            -> classic VNC password auth, with the
#                                password written at start-up by vncpasswd
#                                so it is never baked into the image.
# VNC_SECURITY_TYPES set      -> passed to Xvnc verbatim, overriding both.
# VNC_X509_DIR set            -> generate a self-signed certificate there,
#                                which the X509 VeNCrypt subtypes need.
# That is the only difference between the TigerVNC services in
# docker-compose.yml, so they share this entrypoint and the image.
set -e

trap 'kill -TERM "$XVNC_PID" 2>/dev/null; exit 0' TERM INT

# `docker compose restart` reuses the container filesystem, and a lock left
# by an Xvnc that did not exit cleanly makes the next start die with
# "Server is already active for display 0".
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

set --

if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p /root/.vnc
    printf '%s' "$VNC_PASSWORD" | vncpasswd -f > /root/.vnc/passwd
    chmod 600 /root/.vnc/passwd
    set -- "$@" -PasswordFile /root/.vnc/passwd
fi

if [ -n "$VNC_X509_DIR" ]; then
    mkdir -p "$VNC_X509_DIR"
    # subjectAltName must list the address the tests dial (HOST in
    # tests/functional/utils.py).
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout "$VNC_X509_DIR/key.pem" \
        -out "$VNC_X509_DIR/cert.pem" 2>/dev/null
    chmod 600 "$VNC_X509_DIR/key.pem"
    chmod 644 "$VNC_X509_DIR/cert.pem"
    set -- "$@" -X509Cert "$VNC_X509_DIR/cert.pem" -X509Key "$VNC_X509_DIR/key.pem"
fi

if [ -n "$VNC_SECURITY_TYPES" ]; then
    set -- "$@" -SecurityTypes "$VNC_SECURITY_TYPES"
elif [ -n "$VNC_PASSWORD" ]; then
    set -- "$@" -SecurityTypes VncAuth
else
    set -- "$@" -SecurityTypes None
fi

# BlacklistThreshold avoids lockout due to multiple test runs.
Xvnc :0 \
    "$@" \
    -BlacklistThreshold=500 \
    -rfbport 5900 \
    -geometry "${VNC_GEOMETRY:-1024x768}" \
    -depth 24 \
    -AlwaysShared \
    -localhost=0 &
XVNC_PID=$!

DISPLAY=:0 python3 -m tests.goldens.scene_player &

wait "$XVNC_PID"
