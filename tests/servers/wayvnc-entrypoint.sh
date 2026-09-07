#!/bin/sh
# Setting certificate_file is what makes wayvnc offer VeNCrypt at all, and
# with a username and password it settles on the X509Plain subtype.
set -e

# sway refuses to run as root: it cannot drop privileges it could restore.
id vnc >/dev/null 2>&1 || useradd -m -u 1000 vnc

# Generated at start-up so no key is baked into the image. subjectAltName
# must list the address the tests dial (HOST in tests/functional/utils.py).
mkdir -p /certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout /certs/key.pem \
    -out /certs/cert.pem 2>/dev/null
chmod 600 /certs/key.pem
chmod 644 /certs/cert.pem
chown vnc:vnc /certs/key.pem

GEOMETRY="${VNC_GEOMETRY:-1024x768}"

mkdir -p /home/vnc/.config/wayvnc
cat > /home/vnc/.config/wayvnc/config <<CFG
address=0.0.0.0
port=5900
enable_auth=true
username=${VNC_USERNAME:-vncdotool}
password=${VNC_PASSWORD:-vncdotool}
private_key_file=/certs/key.pem
certificate_file=/certs/cert.pem
CFG

# The headless backend invents an output whose default size is not ours.
cat > /home/vnc/sway.conf <<CFG
output HEADLESS-1 resolution ${GEOMETRY}
exec sleep infinity
CFG

mkdir -p /home/vnc/xdg
chown -R vnc:vnc /home/vnc
chmod 700 /home/vnc/xdg

exec su vnc -s /bin/sh -c '
set -e
export XDG_RUNTIME_DIR=/home/vnc/xdg
export XDG_SESSION_TYPE=wayland
export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
# No GPU in the container, so wlroots software-renders.
export WLR_RENDERER=pixman

sway -c /home/vnc/sway.conf &
SWAY_PID=$!

# wayvnc exits if it starts before the compositor is accepting clients.
for _ in $(seq 30); do
    [ -S "$XDG_RUNTIME_DIR/wayland-1" ] && break
    sleep 0.5
done

WAYLAND_DISPLAY=wayland-1 wayvnc \
    --config=/home/vnc/.config/wayvnc/config \
    0.0.0.0 5900 &
WAYVNC_PID=$!

trap "kill -TERM $WAYVNC_PID $SWAY_PID 2>/dev/null; exit 0" TERM INT
wait "$WAYVNC_PID"
'
