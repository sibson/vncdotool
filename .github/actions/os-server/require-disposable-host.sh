#!/bin/bash
# Refuse to go on unless this machine is a disposable GitHub-hosted runner.
#
# The setup scripts next to this one leave the machine they run on reachable
# for unattended remote control, and deleting a checkout undoes none of it:
# macOS keeps the Remote Management setting and any account created for it,
# Windows keeps the UltraVNC service. So the host has to prove what it is,
# rather than the operator having to remember.
#
# They call this immediately before the first thing that changes the machine,
# not at their own first line: working out which account to authenticate as
# reads and changes nothing, and is worth being able to run anywhere.
#
# RUNNER_ENVIRONMENT is the load-bearing one -- it separates a hosted runner
# from a self-hosted one, which is somebody's real machine. The rest catch a
# local `act` or a step copied out of the workflow.
#
# Both the action and the scripts themselves call this, so running a script
# directly is refused the same way the action would be.
#
# Usage: bash require-disposable-host.sh
set -uo pipefail

# For exercising the setup against a VM. Deliberately a phrase rather than a
# 1, so that nothing sets it by accident and no copy-pasteable command in the
# docs contains it.
if [ "${VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST:-}" = "yes-destroy-this-machine" ]; then
    echo "--- VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST is set, proceeding on a non-runner host"
    exit 0
fi

if [ "${CI:-}" = "true" ] &&
    [ "${GITHUB_ACTIONS:-}" = "true" ] &&
    [ "${RUNNER_ENVIRONMENT:-}" = "github-hosted" ] &&
    [ -n "${GITHUB_RUN_ID:-}" ]; then
    exit 0
fi

echo "refusing to run: this is not a GitHub-hosted runner." >&2
echo "CI=${CI:-<unset>} GITHUB_ACTIONS=${GITHUB_ACTIONS:-<unset>}" >&2
echo "RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-<unset>} GITHUB_RUN_ID=${GITHUB_RUN_ID:-<unset>}" >&2
echo "It would leave this machine reachable for unattended remote control" >&2
echo "with a password that is published in this repository." >&2
echo "" >&2
echo "To exercise it, use a virtual machine you can delete afterwards and set" >&2
echo "VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST as documented in" >&2
echo "tests/servers/screen-sharing/README.md." >&2
exit 1
