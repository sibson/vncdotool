#!/bin/bash
# Collect QEMU's log, process and virtualisation state into a directory, so
# CI can upload it as an artifact.
#
# Never fails: a run that has already gone wrong must not lose the evidence
# to a second error.
#
# Usage: bash tests/servers/qemu-kvm/collect-diagnostics.sh [destination]
set -u

DESTINATION="${1:-diagnostics}"
PORT="${VNCDOTOOL_OS_SERVER_PORT:-5900}"
RUNTIME_DIR="${VNCDOTOOL_QEMU_RUNTIME_DIR:-/tmp/vncdotool-qemu}"

mkdir -p "$DESTINATION"

cp "$RUNTIME_DIR/qemu.log" "$DESTINATION/qemu.log" 2>/dev/null
cp "$RUNTIME_DIR/qemu.pid" "$DESTINATION/qemu.pid" 2>/dev/null

qemu-system-x86_64 --version >"$DESTINATION/version.log" 2>&1
ps -o pid,ppid,etime,args -C qemu-system-x86_64 >"$DESTINATION/process.log" 2>&1
sudo ss -ltnp "sport = :$PORT" >"$DESTINATION/port$PORT.log" 2>&1
# Whether KVM was available at all, and to whom: the difference between an
# accelerated run and a silent fall back to emulation.
ls -l /dev/kvm >"$DESTINATION/kvm.log" 2>&1
id >>"$DESTINATION/kvm.log" 2>&1
lsmod >"$DESTINATION/lsmod.log" 2>&1
sudo dmesg --level=err,warn --since '-10 minutes' >"$DESTINATION/dmesg.log" 2>&1

echo "collected QEMU diagnostics into $DESTINATION"
ls -l "$DESTINATION"
exit 0
