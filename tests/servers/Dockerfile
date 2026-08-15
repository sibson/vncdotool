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
# connections" probe without pulling netcat into every image. That alone
# isn't sufficient readiness, though -- Xvnc in particular starts
# accepting connections the instant it launches, before draw-content.sh's
# backgrounded xlogo has drawn anything, so a port-only check can report
# healthy against a still-flat framebuffer. draw-content.sh only creates
# /tmp/draw-content-ready once xlogo's window is actually mapped, so the
# check also requires that file to exist.
HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900 && test -f /tmp/draw-content-ready'


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
        x11-utils \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY x11vnc-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Extends base's check with the X-side event sink, because this container
# promises two things and the port only evidences one. A dead xev used to
# leave the container "healthy" and every smoke test passing, while the
# event tests polled a log nothing would ever write to again -- the sink
# has to be part of what healthy means, or its absence is discovered as a
# confusing assertion failure thirty tests later.
HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900 && test -f /tmp/draw-content-ready && pgrep -f "xev -root" >/dev/null'

ENTRYPOINT ["/entrypoint.sh"]


# Builds the vncev and example binaries from a pinned release, so neither
# final image needs a compiler. Replaces the old libvncserver.mk host build.
FROM base AS libvncserver-build

ARG LIBVNCSERVER_VERSION=0.9.14

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libssl-dev \
        zlib1g-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fL \
        "https://github.com/LibVNC/libvncserver/archive/refs/tags/LibVNCServer-${LIBVNCSERVER_VERSION}.tar.gz" \
        -o /tmp/libvncserver.tar.gz \
    && mkdir -p /tmp/libvncserver \
    && tar xzf /tmp/libvncserver.tar.gz --strip-components=1 -C /tmp/libvncserver \
    && rm /tmp/libvncserver.tar.gz

# Named targets rather than `all`: skips the SDL/GTK example clients.
WORKDIR /tmp/libvncserver
RUN cmake -DCMAKE_BUILD_TYPE=Release . \
    && cmake --build . --target examples_vncev examples_example -- -j"$(nproc)"


# Event sink: prints events, renders no desktop, so the HEALTHCHECK drops
# base's draw-content marker.
FROM base AS vncev

RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=libvncserver-build /tmp/libvncserver/examples/vncev /usr/local/bin/vncev
COPY --from=libvncserver-build /tmp/libvncserver/libvncserver.so* /usr/local/lib/
RUN ldconfig

HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900'

ENTRYPOINT ["vncev", "-rfbport", "5900", "-rfbwait", "1000"]


# Self-animated canvas, so there is no draw-content.sh marker to wait for.
FROM base AS libvncserver-example

RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=libvncserver-build /tmp/libvncserver/examples/example /usr/local/bin/example
COPY --from=libvncserver-build /tmp/libvncserver/libvncserver.so* /usr/local/lib/
RUN ldconfig

HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900'

ENTRYPOINT ["example", "-rfbport", "5900", "-rfbwait", "1000"]
