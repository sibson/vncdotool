#!/bin/sh
# Start a KasmVNC (Xkasmvnc) server, no authentication, optionally over TLS.
set -e

trap 'kill -TERM "$XVNC_PID" 2>/dev/null; exit 0' TERM INT

rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

# KasmVNC guards the websocket with HTTP basic auth of its own, on top of
# whatever RFB security type is in force.
set -- -DisableBasicAuth 1

if [ -n "${KASMVNC_TLS:-}" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout /tmp/server.key -out /tmp/server.crt >/dev/null 2>&1
    cat /tmp/server.key /tmp/server.crt > /tmp/server.pem
    set -- "$@" -cert /tmp/server.pem -sslOnly 1
else
    set -- "$@" -sslOnly 0
fi

Xkasmvnc :0 \
    "$@" \
    -websocketPort 5900 \
    -interface 0.0.0.0 \
    -SecurityTypes None \
    -geometry "${VNC_GEOMETRY:-1024x768}" \
    -depth 24 \
    -AlwaysShared &
XVNC_PID=$!

DISPLAY=:0 python3 -m tests.goldens.scene_player &

wait "$XVNC_PID"
