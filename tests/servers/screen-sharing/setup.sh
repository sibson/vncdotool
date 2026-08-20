#!/bin/bash
# Enable Apple Screen Sharing / Remote Management on this macOS machine and
# set up the local user vncdotool authenticates as.
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

# Connecting as a user who is not the one holding the console costs a fast
# user switch: a full first login for that account, whose UserAccountUpdater
# and Setup Assistant phases ran for around a minute on a hosted runner and
# left the session sitting at loginwindow -- which is also why the
# framebuffer came back black. Reusing the console owner attaches to the
# session that is already logged in, so no login happens at all; it needs a
# password we know, hence the reset.
#
# Resetting an existing account's password is destructive and sets it to a
# password published in this repository, so it happens only when asked for
# by name: an unset VNCDOTOOL_OS_SERVER_RESET_PASSWORD stops the script
# instead, which is what a developer running this against their own login
# gets.
setup_user() {
    if id "$USERNAME" >/dev/null 2>&1; then
        if [ "${VNCDOTOOL_OS_SERVER_RESET_PASSWORD:-}" != "1" ]; then
            echo "user $USERNAME already exists." >&2
            echo "Set VNCDOTOOL_OS_SERVER_RESET_PASSWORD=1 to reset its password to" >&2
            echo "\$VNCDOTOOL_OS_SERVER_PASSWORD, or point" >&2
            echo "VNCDOTOOL_OS_SERVER_USERNAME at an account that does not exist yet." >&2
            echo "Only do the former on a throwaway machine: the password is public." >&2
            return 1
        fi
        echo "--- resetting the password of the existing user $USERNAME"
        sudo sysadminctl -resetPasswordFor "$USERNAME" -newPassword "$PASSWORD"
        return
    fi
    echo "--- creating local user $USERNAME"
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
    # bash's own /dev/tcp rather than nc, matching how the Docker servers
    # probe themselves -- one less tool the machine has to have.
    echo "--- waiting up to ${WAIT_SECONDS}s for port $PORT"
    local deadline=$((SECONDS + WAIT_SECONDS))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
            echo "port $PORT is open"
            return 0
        fi
        sleep 2
    done
    echo "Screen Sharing never started listening on port $PORT" >&2
    return 1
}

setup_user
enable_remote_management
keep_display_awake
wait_for_port

echo "Screen Sharing is serving on 127.0.0.1:$PORT for user $USERNAME"
