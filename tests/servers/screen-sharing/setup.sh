#!/bin/bash
# Enable Apple Screen Sharing / Remote Management on this macOS machine and
# set up the local user vncdotool authenticates as.
#
# Used to give vncdotool's functional tests (tests/functional/test_os_servers.py)
# a live macOS server on 127.0.0.1; see README.md in this directory for what
# does and doesn't work on a hosted runner.
#
# This turns the machine into an unattended remote-control target with a
# password published in this repository, so it refuses to run anywhere but a
# GitHub-hosted runner -- see require_disposable_host below.
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

# Everything below this point is destructive to the machine it runs on, and
# the damage is not undone by deleting a checkout: an account exists, remote
# control is enabled, and the password for both is public. So the machine has
# to prove it is disposable before anything happens, rather than the operator
# having to remember not to run this. GitHub sets all four of these on a
# hosted runner and RUNNER_ENVIRONMENT distinguishes one from a self-hosted
# runner, which is somebody's real machine.
#
# The escape hatch exists for developing this script against a VM. It is
# deliberately a phrase rather than a 1: nothing should set it by accident,
# and no copy-pasteable command line in the docs contains it.
require_disposable_host() {
    if [ "${VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST:-}" = "yes-destroy-this-machine" ]; then
        echo "--- VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST is set, proceeding on a non-runner host"
        return
    fi
    if [ "${CI:-}" = "true" ] &&
        [ "${GITHUB_ACTIONS:-}" = "true" ] &&
        [ "${RUNNER_ENVIRONMENT:-}" = "github-hosted" ] &&
        [ -n "${GITHUB_RUN_ID:-}" ]; then
        return
    fi
    echo "refusing to run: this is not a GitHub-hosted runner." >&2
    echo "CI=${CI:-<unset>} GITHUB_ACTIONS=${GITHUB_ACTIONS:-<unset>}" >&2
    echo "RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-<unset>} GITHUB_RUN_ID=${GITHUB_RUN_ID:-<unset>}" >&2
    echo "It would create or repassword a local account, switch on Remote" >&2
    echo "Management, and leave this machine reachable with a password that is" >&2
    echo "published in this repository." >&2
    echo "" >&2
    echo "To exercise it, use a virtual machine you can delete afterwards and" >&2
    echo "set VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST as documented in README.md." >&2
    return 1
}

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

require_disposable_host
setup_user
enable_remote_management
keep_display_awake
wait_for_port

echo "Screen Sharing is serving on 127.0.0.1:$PORT for user $USERNAME"
