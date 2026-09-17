#!/bin/sh
set -e

{
    # An X server refuses connections until it is listening, and python-xlib
    # raises on a refused one rather than retrying.
    for _ in $(seq 1 30); do
        DISPLAY=:0 xdpyinfo >/dev/null 2>&1 && break
        sleep 0.5
    done

    for _ in $(seq 1 60); do
        DISPLAY=:0 python3 -m tests.goldens.scene_player || true
        echo "exited; restarting the scene player"
        sleep 0.5
    done

    echo "kept exiting; taking the container down with it"
    kill -TERM 1
} 2>&1 | sed -u 's/^/scene-player: /'
