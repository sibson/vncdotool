#!/bin/bash
# Turn this macOS machine into a live Screen Sharing server for
# tests/functional/test_os_servers.py, and wait until it serves.
#
# Driven by .github/actions/os-server/action.yml; see
# tests/servers/screen-sharing/README.md for what the server does and doesn't
# prove. Reads PORT, WAIT_SECONDS and CAFFEINATE_SECONDS from the environment,
# and publishes the account it authenticated as through $GITHUB_ENV.
#
# It never creates an account. The only account it can use is the one already
# holding the console, so on a machine that does not auto-login there is no
# /etc/kcpassword, nothing to authenticate as, and this stops before doing
# anything at all. What follows the check does change the machine -- Remote
# Management goes on -- which is what require-disposable-host.sh gates.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KICKSTART=/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart

PORT="${PORT:-5900}"
WAIT_SECONDS="${WAIT_SECONDS:-60}"
CAFFEINATE_SECONDS="${CAFFEINATE_SECONDS:-1200}"

KCPASSWORD=/etc/kcpassword
# Auto-login stores the password obfuscated rather than hashed, because
# loginwindow has to replay it: XORed against this key, repeated, and
# NUL-padded to a multiple of its length.
KCPASSWORD_KEY=(125 137 82 35 210 188 221 234 163 185 31)

# Reads the file's bytes as decimals on stdin and prints the password.
#
# Rejecting anything outside printable ASCII is what stops a file written in
# some other format being read as a password: actions/runner-images#5231
# shipped images whose kcpassword was UTF-8 encoded rather than raw bytes, and
# the wrong key or a changed layout produces the same kind of noise. It also
# means the value cannot contain a newline, which matters because it is
# written to $GITHUB_ENV, where a newline would start a variable of its own.
decode_kcpassword() {
    local byte clear i=0 password=""

    while read -r byte; do
        if [ -z "$byte" ]; then
            continue
        fi
        clear=$((byte ^ KCPASSWORD_KEY[i % ${#KCPASSWORD_KEY[@]}]))
        i=$((i + 1))
        # Padding is NUL bytes appended to the password, so the first one ends it.
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

# Authenticating as anyone but the console owner fast-user-switches into that
# account's first login, which cost this job about a minute (see
# tests/servers/screen-sharing/README.md). The console owner's own password
# cannot be set -- it holds a secure token -- but it does not need to be:
# these images enable auto-login (runner-images
# images/macos/scripts/build/configure-autologin.sh), so loginwindow has to be
# able to replay the password, and macOS keeps it in /etc/kcpassword XORed
# against a published 11-byte key. The account logging itself in at boot is
# proof the file matches.
USERNAME=$(stat -f %Su /dev/console)
if ! PASSWORD=$(sudo od -An -v -tu1 "$KCPASSWORD" | tr -s ' ' '\n' | decode_kcpassword); then
    echo "could not read the console owner's auto-login password, so there is" >&2
    echo "no account to authenticate as. A machine that does not auto-login" >&2
    echo "cannot host this server without being given an account of its own," >&2
    echo "which is deliberately not something this script will do." >&2
    exit 1
fi
if [ -z "$PASSWORD" ]; then
    # decode_kcpassword fails on an empty password, so reaching here means
    # something between it and this assignment succeeded while producing
    # nothing. sysadminctl has already taught us what a tool that lies about
    # failing costs to debug.
    echo "recovered an empty password without an error" >&2
    exit 1
fi
echo "::add-mask::$PASSWORD"
echo "--- authenticating as the console owner $USERNAME, no user switch"

# Everything above this line reads. Everything below it changes the machine,
# which is why the check sits here rather than at the top: Remote Management
# gets switched on, and a checkout deletion does not switch it back off.
bash "$HERE/require-disposable-host.sh"

# The tests read these, and which account we ended up with is decided here
# rather than by the workflow.
if [ -n "${GITHUB_ENV:-}" ]; then
    {
        echo "VNCDOTOOL_OS_SERVER_USERNAME=$USERNAME"
        echo "VNCDOTOOL_OS_SERVER_PASSWORD=$PASSWORD"
    } >>"$GITHUB_ENV"
fi

# Whichever path set it, prove the account authenticates before spending three
# minutes of readiness retries finding out it doesn't.
if ! dscl . -authonly "$USERNAME" "$PASSWORD" >/dev/null 2>&1; then
    echo "$USERNAME does not authenticate with the configured password" >&2
    exit 1
fi

# -users/-privs grants that user full control; Screen Sharing itself is
# socket-activated on 5900 and needs no separate enabling.
echo "--- activating Remote Management for $USERNAME"
sudo "$KICKSTART" \
    -activate -configure -access -on \
    -users "$USERNAME" -privs -all \
    -restart -agent

# Rules out display sleep / App Nap as a cause of an empty framebuffer.
echo "--- holding the display awake in the background"
nohup caffeinate -d -i -u -t "$CAFFEINATE_SECONDS" >/dev/null 2>&1 &
disown

# bash's own /dev/tcp rather than nc, matching how the Docker servers probe
# themselves -- one less tool the machine has to have.
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
