#!/bin/sh
# Start a TigerVNC (Xvnc) server with classic VNC password authentication
# and draw a trivial X client on it so captures aren't pure black.
set -e

trap 'kill -TERM "$XVNC_PID" 2>/dev/null; exit 0' TERM INT

VNC_PASSWORD="${VNC_PASSWORD:-vncdotool}"
mkdir -p /root/.vnc
printf '%s' "$VNC_PASSWORD" | vncpasswd -f > /root/.vnc/passwd
chmod 600 /root/.vnc/passwd

Xvnc :0 \
    -SecurityTypes VncAuth \
    -PasswordFile /root/.vnc/passwd \
    -rfbport 5900 \
    -geometry 1024x768 \
    -depth 24 \
    -AlwaysShared \
    -localhost=0 &
XVNC_PID=$!

export DISPLAY=:0
for _ in $(seq 1 30); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

xlogo -geometry 200x200+50+50 &

wait "$XVNC_PID"
