#!/bin/bash
# Turn this macOS machine into a live Screen Sharing server for
# tests/functional/test_os_servers.py. See
# tests/servers/screen-sharing/README.md.
set -euo pipefail

KICKSTART=/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart

PORT="${PORT:-5900}"
WAIT_SECONDS="${WAIT_SECONDS:-60}"
CAFFEINATE_SECONDS="${CAFFEINATE_SECONDS:-1200}"

KCPASSWORD=/etc/kcpassword
# Auto-login stores the password obfuscated rather than hashed, because
# loginwindow has to replay it: XORed against this key, repeated, and
# NUL-padded to a multiple of its length.
KCPASSWORD_KEY=(125 137 82 35 210 188 221 234 163 185 31)

# Remote Management stays on after this job, and after the checkout is gone.
require_disposable_host() {
    if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ "${RUNNER_ENVIRONMENT:-}" = "github-hosted" ]; then
        return
    fi
    echo "refusing to run: RUNNER_ENVIRONMENT=${RUNNER_ENVIRONMENT:-<unset>} is not" >&2
    echo "a GitHub-hosted runner, and this leaves the machine remotely controllable." >&2
    exit 1
}

# Reads the file's bytes as decimals on stdin and prints the password.
#
# Refusing anything outside printable ASCII is what tells a password from a
# file in some other format: runner-images once shipped kcpassword written as
# UTF-8 rather than raw bytes. It also keeps a newline out of the value, which
# would start a variable of its own in $GITHUB_ENV.
decode_kcpassword() {
    local byte clear i=0 password=""

    while read -r byte; do
        if [ -z "$byte" ]; then
            continue
        fi
        clear=$((byte ^ KCPASSWORD_KEY[i % ${#KCPASSWORD_KEY[@]}]))
        i=$((i + 1))
        if [ "$clear" -eq 0 ]; then
            break
        fi
        if [ "$clear" -lt 32 ] || [ "$clear" -gt 126 ]; then
            echo "$KCPASSWORD did not decode to a printable password" >&2
            return 1
        fi
        password+=$(printf "\\$(printf '%03o' "$clear")")
    done

    if [ -z "$password" ]; then
        echo "$KCPASSWORD decoded to nothing" >&2
        return 1
    fi
    printf '%s' "$password"
}

USERNAME=$(stat -f %Su /dev/console)
if ! PASSWORD=$(sudo od -An -v -tu1 "$KCPASSWORD" | tr -s ' ' '\n' | decode_kcpassword); then
    echo "could not read the console owner's auto-login password, so there is" >&2
    echo "no account to authenticate as. A machine that does not auto-login" >&2
    echo "cannot host this server without being given an account of its own," >&2
    echo "which is deliberately not something this script will do." >&2
    exit 1
fi
if [ -z "$PASSWORD" ]; then
    # decode_kcpassword already fails on an empty password, so this catches
    # something in the pipeline before it exiting 0 with nothing to show.
    echo "recovered an empty password without an error" >&2
    exit 1
fi
echo "::add-mask::$PASSWORD"
echo "--- authenticating as the console owner $USERNAME, no user switch"

# Everything above this line only reads.
require_disposable_host

# tests/functional/vncservers.py reads these.
if [ -n "${GITHUB_ENV:-}" ]; then
    {
        echo "VNCDOTOOL_OS_SERVER_USERNAME=$USERNAME"
        echo "VNCDOTOOL_OS_SERVER_PASSWORD=$PASSWORD"
    } >>"$GITHUB_ENV"
fi

# A password that does not authenticate otherwise surfaces as three minutes of
# readiness retries against a server that was never the problem.
if ! dscl . -authonly "$USERNAME" "$PASSWORD" >/dev/null 2>&1; then
    echo "$USERNAME does not authenticate with the configured password" >&2
    exit 1
fi

# Screen Sharing is socket-activated on 5900: nothing has to be started beyond
# this, and the first connection is what launches the server.
echo "--- activating Remote Management for $USERNAME"
sudo "$KICKSTART" \
    -activate -configure -access -on \
    -users "$USERNAME" -privs -all \
    -restart -agent

# Rules out display sleep / App Nap as a cause of an empty framebuffer.
echo "--- holding the display awake in the background"
nohup caffeinate -d -i -u -t "$CAFFEINATE_SECONDS" >/dev/null 2>&1 &
disown

echo "--- waiting up to ${WAIT_SECONDS}s for port $PORT"
deadline=$((SECONDS + WAIT_SECONDS))
while [ "$SECONDS" -lt "$deadline" ]; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
        echo "Screen Sharing is serving on 127.0.0.1:$PORT for user $USERNAME"
        exit 0
    fi
    sleep 2
done

echo "Screen Sharing never started listening on port $PORT" >&2
exit 1
