# Minimal Xvfb + x11vnc server, no authentication.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        x11-apps \
        xauth \
        netcat-openbsd \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5900

HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD nc -z 127.0.0.1 5900

ENTRYPOINT ["/entrypoint.sh"]
