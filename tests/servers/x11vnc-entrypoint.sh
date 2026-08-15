#!/bin/sh
# Start a virtual X display (Xvfb) with x11vnc serving it, no authentication.
set -e

# Restarting a stopped container reuses its filesystem, and Xvfb refuses to
# start on the lock the previous run left behind.
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 /tmp/draw-content-ready

Xvfb :0 -screen 0 1024x768x24 &
XVFB_PID=$!
trap 'kill -TERM "$XVFB_PID" 2>/dev/null; exit 0' TERM INT

DISPLAY=:0 /draw-content.sh &

# X-side event sink: confirms an event arrived as a real X event, not just
# that the client put it on the wire. Prefixed so it greps cleanly out of
# `docker compose logs x11vnc`.
#
# xdpyinfo succeeding does not mean the next X client can connect -- Xvfb
# accepts connections before it has finished initialising -- so xev is
# restarted rather than started once. If it never comes up, PID 1 goes with
# it: this container serves VNC *and* observes X events, and one without the
# other is a container that passes every smoke test while silently answering
# no event question correctly.
(
    for _ in $(seq 1 30); do
        DISPLAY=:0 xdpyinfo >/dev/null 2>&1 && break
        sleep 0.5
    done
    for _ in $(seq 1 60); do
        # `|| true` is load-bearing under `set -e`: a failed xev would
        # otherwise take this subshell down with it, which is the very
        # thing being guarded against.
        DISPLAY=:0 xev -root || true
        echo "xev exited; restarting the X-side event sink"
        sleep 0.5
    done
    echo "xev kept exiting; taking the container down with it"
    kill -TERM 1
) 2>&1 | sed -u 's/^/xev: /' &

# x11vnc exits 1 if the display isn't up yet, and Xvfb needs a moment.
for _ in $(seq 1 30); do
    DISPLAY=:0 xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

exec x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet
