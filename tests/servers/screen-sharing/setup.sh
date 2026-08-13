#!/bin/bash
# Enable Apple Screen Sharing / Remote Management on this macOS machine and
# create the local user vncdotool authenticates as.
#
# Used to give vncdotool's functional tests (tests/functional/test_os_servers.py)
# a live macOS server on 127.0.0.1; see README.md in this directory for what
# does and doesn't work on a hosted runner.
#
# This turns the machine into an unattended remote-control target with a
# throwaway password, so run it only on a throwaway machine.
#
# Usage: sudo bash tests/servers/screen-sharing/setup.sh
set -euo pipefail

# Defaults match tests/functional/vncservers.py, which reads the same
# environment variables.
USERNAME="${VNCDOTOOL_OS_SERVER_USERNAME:-vncspike}"
PASSWORD="${VNCDOTOOL_OS_SERVER_PASSWORD:-vncspike1}"
PORT="${VNCDOTOOL_OS_SERVER_PORT:-5900}"
WAIT_SECONDS="${VNCDOTOOL_OS_SERVER_WAIT:-60}"

KICKSTART=/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart

create_user() {
    echo "--- creating local user $USERNAME"
    if id "$USERNAME" >/dev/null 2>&1; then
        echo "user $USERNAME already exists"
        return
    fi
    sudo sysadminctl -addUser "$USERNAME" -fullName "vncdotool test user" -password "$PASSWORD"
}

enable_remote_management() {
    echo "--- activating Remote Management for $USERNAME"
    # -users/-privs grants that user full control; Screen Sharing itself is
    # socket-activated on 5900 and needs no separate enabling.
    sudo "$KICKSTART" \
        -activate -configure -access -on \
        -users "$USERNAME" -privs -all \
        -restart -agent
}

keep_display_awake() {
    # Rules out display sleep / App Nap as a cause of an empty framebuffer.
    echo "--- holding the display awake in the background"
    nohup caffeinate -d -i -u -t "${VNCDOTOOL_OS_SERVER_CAFFEINATE:-1200}" \
        >/dev/null 2>&1 &
    disown
}

wait_for_port() {
    echo "--- waiting up to ${WAIT_SECONDS}s for port $PORT"
    local deadline=$((SECONDS + WAIT_SECONDS))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if nc -z -w2 127.0.0.1 "$PORT" 2>/dev/null; then
            echo "port $PORT is open"
            return 0
        fi
        sleep 2
    done
    echo "Screen Sharing never started listening on port $PORT" >&2
    return 1
}

create_user
enable_remote_management
keep_display_awake
wait_for_port

echo "Screen Sharing is serving on 127.0.0.1:$PORT for user $USERNAME"
