#!/bin/sh
# Run QEMU's own VNC server, optionally over TLS.
set -eu

# RFB and the WebSocket cannot share one display, and the fleet's mapping
# and healthcheck want 5900, so RFB goes to :10.
VNC_ARGS=":10,websocket=5900"

if [ -n "${QEMU_VNC_TLS:-}" ]; then
    mkdir -p /tls
    # QEMU rejects either file in the other's role: a CA whose basicConstraints
    # do not say CA, or a server certificate whose do.
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=vncdotool-test-ca" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -keyout /tls/ca-key.pem -out /tls/ca-cert.pem >/dev/null 2>&1
    openssl req -newkey rsa:2048 -nodes \
        -subj "/CN=localhost" \
        -keyout /tls/server-key.pem -out /tls/server.csr >/dev/null 2>&1
    openssl x509 -req -in /tls/server.csr -days 3650 \
        -CA /tls/ca-cert.pem -CAkey /tls/ca-key.pem -CAcreateserial \
        -extfile /dev/stdin -out /tls/server-cert.pem >/dev/null 2>&1 <<EOF
subjectAltName=DNS:localhost,IP:127.0.0.1
basicConstraints=critical,CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
    rm -f /tls/server.csr
    set -- -object "tls-creds-x509,id=tls0,endpoint=server,dir=/tls,verify-peer=off"
    VNC_ARGS="${VNC_ARGS},tls-creds=tls0"
else
    set --
fi

# No disk, so the firmware's own screen is the framebuffer. SeaBIOS blinks a
# VGA text cursor, so two captures of an idle machine differ; the UEFI shell
# holds still. Without -net none OVMF retries PXE forever and the screen
# scrolls.
exec qemu-system-x86_64 \
    -m 128 \
    -display none \
    -net none \
    -bios /usr/share/OVMF/OVMF_CODE.fd \
    -vnc "$VNC_ARGS" \
    "$@"
