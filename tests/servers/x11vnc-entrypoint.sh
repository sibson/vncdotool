#!/bin/sh
# Start a virtual X display (Xvfb) with x11vnc serving it, no authentication.
set -e

Xvfb :0 -screen 0 1024x768x24 &
XVFB_PID=$!
trap 'kill -TERM "$XVFB_PID" 2>/dev/null; exit 0' TERM INT

DISPLAY=:0 /draw-content.sh &

# X-side event sink: confirms an event arrived as a real X event, not just
# that the client put it on the wire. Prefixed so it greps cleanly out of
# `docker compose logs x11vnc`.
#
# xev is supervised rather than started once. A successful xdpyinfo probe
# does not mean the next client can connect -- Xvfb accepts connections
# before it has finished initialising -- and an xev that loses that race
# dies with "unable to open display" and never comes back. Nothing else
# notices: x11vnc keeps serving, the container stays healthy, and every
# event test for the rest of the run polls a log the dead sink will never
# write to again. Restarting it turns that from a poisoned run into a
# half-second gap.
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
    echo "xev kept exiting; giving up on the X-side event sink"
) 2>&1 | sed -u 's/^/xev: /' &

# x11vnc exits 1 if the display isn't up yet, and Xvfb needs a moment.
for _ in $(seq 1 30); do
    DISPLAY=:0 xdpyinfo >/dev/null 2>&1 && break
    sleep 0.5
done

exec x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet
