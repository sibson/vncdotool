# Minimal TigerVNC (Xvnc) server, no authentication.
#
# Deliberately built from a small in-repo Dockerfile rather than a
# third-party desktop image so the exact server version is controlled by
# apt in the base distro rather than by whatever a random upstream image
# happens to bundle.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tigervnc-standalone-server \
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
