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
        x11-utils \
        xauth \
        procps \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

COPY draw-content.sh /draw-content.sh
RUN chmod +x /draw-content.sh

EXPOSE 5900

# Liveness only: the process came up and bound its port. Whether the server
# is ready to serve is decided out of band by
# `tests/functional/wait_for_servers.py docker`, which connects, captures,
# and requires the content the server is supposed to render -- the same
# assertion the tests make, so there is one definition of readiness for the
# Docker fleet and the OS-hosted servers rather than a weaker in-container
# imitation of it.
#
# This must never open an RFB connection. Xvnc counts every connection
# closed before a successful authentication towards BlacklistThreshold
# (default 5), so a probe that connects and hangs up blacklists 127.0.0.1
# within ~10s and refuses every later session. Completing the RFB version
# handshake first does not help -- measured against TigerVNC 1.12.0, a bare
# connect, a version exchange, and a version-plus-security-types exchange
# all trip the counter identically. `ss` reads the kernel's socket table
# instead, so the port is confirmed listening without a connection existing.
HEALTHCHECK --interval=2s --timeout=2s --start-period=5s --retries=30 \
    CMD ss -H -ltn 'sport = :5900' | grep -q .


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

# Extends base's check with the event sink: the port evidences only half of
# what this container promises, and the sink loses a startup race often
# enough that readiness has to wait for it.
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


# Event sink: prints events and renders no desktop, so vncservers.py marks
# it renders_desktop=False and readiness stops at the handshake.
FROM base AS vncev

RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=libvncserver-build /tmp/libvncserver/examples/vncev /usr/local/bin/vncev
COPY --from=libvncserver-build /tmp/libvncserver/libvncserver.so* /usr/local/lib/
RUN ldconfig

ENTRYPOINT ["vncev", "-rfbport", "5900", "-rfbwait", "1000"]


# Self-animated canvas, so it draws its own content rather than needing
# draw-content.sh to put an X client on the screen.
FROM base AS libvncserver-example

RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=libvncserver-build /tmp/libvncserver/examples/example /usr/local/bin/example
COPY --from=libvncserver-build /tmp/libvncserver/libvncserver.so* /usr/local/lib/
RUN ldconfig

ENTRYPOINT ["example", "-rfbport", "5900", "-rfbwait", "1000"]
