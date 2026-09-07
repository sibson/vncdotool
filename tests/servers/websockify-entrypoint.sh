#!/bin/sh
# Run websockify in front of another fleet member, optionally over TLS.
set -eu

if [ -n "${WEBSOCKIFY_TLS:-}" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout /tmp/server.key -out /tmp/server.crt >/dev/null 2>&1
    cat /tmp/server.key /tmp/server.crt >/tmp/server.pem
    set -- --cert=/tmp/server.pem --ssl-only 0.0.0.0:5900 "$@"
else
    set -- 0.0.0.0:5900 "$@"
fi

exec websockify "$@"
