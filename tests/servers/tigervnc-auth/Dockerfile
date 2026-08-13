# Minimal TigerVNC (Xvnc) server with VNC password authentication.
#
# The password is set at container start via the VNC_PASSWORD environment
# variable (default "vncdotool") using the standard vncpasswd tool, so it
# is never baked into the image.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tigervnc-standalone-server \
        tigervnc-common \
        tigervnc-tools \
        x11-apps \
        xauth \
        netcat-openbsd \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV VNC_PASSWORD=vncdotool

EXPOSE 5900

HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD nc -z 127.0.0.1 5900

ENTRYPOINT ["/entrypoint.sh"]
