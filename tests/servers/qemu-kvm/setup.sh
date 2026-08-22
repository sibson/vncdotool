#!/bin/bash
# Start a raw QEMU VNC server on this Linux machine -- no container, no disk
# and no guest OS, so what answers on 127.0.0.1 is QEMU's own RFB server
# drawing the firmware's framebuffer.
#
# Used to give vncdotool's functional tests (tests/functional/test_os_servers.py)
# a live QEMU server; see README.md in this directory for what that does and
# doesn't prove.
#
# This leaves an unauthenticated VNC server listening on loopback, so run it
# only on a throwaway machine.
#
# Usage: bash tests/servers/qemu-kvm/setup.sh
set -euo pipefail

# Defaults match tests/functional/vncservers.py, which reads the same
# environment variables.
PORT="${VNCDOTOOL_OS_SERVER_PORT:-5900}"
WAIT_SECONDS="${VNCDOTOOL_OS_SERVER_WAIT:-60}"

# kvm is the point of this server on a Linux runner; a developer's machine
# without /dev/kvm (macOS, a VM without nested virtualisation) can set
# VNCDOTOOL_QEMU_ACCEL=tcg to exercise the same script under emulation.
ACCEL="${VNCDOTOOL_QEMU_ACCEL:-kvm}"
MEMORY="${VNCDOTOOL_QEMU_MEMORY:-256}"

QEMU=qemu-system-x86_64
RUNTIME_DIR="${VNCDOTOOL_QEMU_RUNTIME_DIR:-/tmp/vncdotool-qemu}"
PIDFILE="$RUNTIME_DIR/qemu.pid"
LOGFILE="$RUNTIME_DIR/qemu.log"

# QEMU takes a display number, not a port: :0 is 5900.
DISPLAY_NUMBER=$((PORT - 5900))

install_qemu() {
    echo "--- installing $QEMU"
    if command -v "$QEMU" >/dev/null 2>&1; then
        echo "$QEMU already installed: $("$QEMU" --version | head -1)"
        return
    fi
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends qemu-system-x86
}

grant_kvm_access() {
    if [ "$ACCEL" != "kvm" ]; then
        echo "--- skipping /dev/kvm setup, accelerator is $ACCEL"
        return
    fi
    if [ ! -e /dev/kvm ]; then
        echo "no /dev/kvm on this machine; set VNCDOTOOL_QEMU_ACCEL=tcg to run without it" >&2
        return 1
    fi
    if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "--- /dev/kvm is already usable by $(id -un)"
        return
    fi
    # GitHub's hosted runners ship /dev/kvm as root:kvm 0660 and the runner
    # user is not in the kvm group, so opening it up is part of setup rather
    # than something the image has done for us.
    echo "--- opening /dev/kvm up to all users"
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' |
        sudo tee /etc/udev/rules.d/99-kvm-all-users.rules >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=kvm
    if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
        ls -l /dev/kvm >&2
        echo "/dev/kvm is still not readable and writable by $(id -un)" >&2
        return 1
    fi
}

start_qemu() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "--- QEMU is already running as pid $(cat "$PIDFILE")"
        return
    fi

    echo "--- starting $QEMU on display :$DISPLAY_NUMBER with -accel $ACCEL"
    mkdir -p "$RUNTIME_DIR"
    rm -f "$PIDFILE"
    # No -drive and no -kernel: with nothing to boot, the machine sits at the
    # firmware's "no bootable device" screen, which is a perfectly good
    # framebuffer to serve and needs no guest image to download.
    #
    # 127.0.0.1: prefix matters. A bare -vnc :0 listens on every interface,
    # and this server has no authentication at all -- QEMU only asks for a
    # password when started with `password=on`, and even then the password
    # itself has to be set afterwards over the monitor.
    "$QEMU" \
        -name vncdotool \
        -accel "$ACCEL" \
        -m "$MEMORY" \
        -vga std \
        -vnc "127.0.0.1:$DISPLAY_NUMBER" \
        -pidfile "$PIDFILE" \
        -D "$LOGFILE" \
        -daemonize
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
    echo "QEMU never started listening on port $PORT" >&2
    return 1
}

enable_test_registration() {
    # tests/functional/vncservers.py only registers QEMU_KVM on Linux when
    # this is set -- ubuntu-latest also runs ci.yml's unrelated Tier 1
    # Docker-fleet job, which never runs this script, and platform alone
    # can't tell the two jobs apart.
    export VNCDOTOOL_OS_SERVER_LINUX=1
    if [ -n "${GITHUB_ENV:-}" ]; then
        echo "VNCDOTOOL_OS_SERVER_LINUX=1" >>"$GITHUB_ENV"
    else
        echo "--- export VNCDOTOOL_OS_SERVER_LINUX=1 in your shell before" >&2
        echo "running the test suite outside of this script's own process." >&2
    fi
}

install_qemu
grant_kvm_access
start_qemu
wait_for_port
enable_test_registration

echo "QEMU is serving on 127.0.0.1:$PORT (pidfile $PIDFILE, log $LOGFILE)"
