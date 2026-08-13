# Every VNC test server image, as stages off one shared base.
#
# Deliberately built from a small in-repo Dockerfile rather than a
# third-party desktop image so the exact server version is controlled by
# apt in the base distro rather than by whatever a random upstream image
# happens to bundle.
#
# docker-compose.yml selects a stage per service with `target:`. The base
# stage holds everything the servers have in common -- an X client to draw
# so captures aren't pure black, and the readiness probe -- so adding a
# server means one stage, not another near-copy of this file.

FROM debian:bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        x11-apps \
        xauth \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY draw-content.sh /draw-content.sh
RUN chmod +x /draw-content.sh

EXPOSE 5900

# bash's /dev/tcp rather than `nc`: same "is the RFB port accepting
# connections" probe without pulling netcat into every image.
HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900'


# TigerVNC's own X server. Serves with no authentication by default, or
# with classic VNC password auth when VNC_PASSWORD is set -- see
# tigervnc-entrypoint.sh. tigervnc-tools is where Debian keeps vncpasswd.
FROM base AS tigervnc

RUN apt-get update && apt-get install -y --no-install-recommends \
        tigervnc-standalone-server \
        tigervnc-common \
        tigervnc-tools \
    && rm -rf /var/lib/apt/lists/*

COPY tigervnc-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]


# x11vnc exporting a plain Xvfb display -- a different shape from TigerVNC
# (a VNC server bolted onto an existing X server) and so worth covering.
FROM base AS x11vnc

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
    && rm -rf /var/lib/apt/lists/*

COPY x11vnc-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
