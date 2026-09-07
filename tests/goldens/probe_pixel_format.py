"""Manually probe a live server's real wire behaviour against a requested
PixelFormat, independent of what the server declares.

For debugging pixel-format/CPIXEL quirks like #483 (a server narrowing ZRLE
regardless of a declared or requested depth): connects with a real client,
requests the given format (or nothing, to see the server's own native
choice), and reports whether the encoding decoded cleanly.

Run by hand, against the fleet (`make servers-up`) or an OS-hosted server
this host has set up per tests/servers/*/README.md:

    uv run python -m tests.goldens.probe_pixel_format --server tigervnc --depth 32
    uv run python -m tests.goldens.probe_pixel_format --server libvncserver-example --native
    uv run python -m tests.goldens.probe_pixel_format --server x11vnc --pixel-format rgbx8888 --depth 32 --encoding zrle
    uv run python -m tests.goldens.probe_pixel_format --server screen-sharing --depth 32

Drives the Twisted reactor (via vncdotool.api), so it must run as its own
process, never inside a test.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import time

from vncdotool import api, decoders
from vncdotool.client import VNCDoToolFactory
from vncdotool.pixelformat import PIXEL_FORMATS

from tests.functional.utils import DOCKER_SERVERS, HOST, os_servers

# os_servers() is only the current platform's -- an OS-hosted server can't
# be dialled into from anywhere else, so cross-platform names don't belong
# in this process's list at all.
SERVERS_BY_NAME = {server.name: server for server in DOCKER_SERVERS + os_servers()}
CONNECT_SETTLE = 0.5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", choices=sorted(SERVERS_BY_NAME), required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--pixel-format", choices=sorted(PIXEL_FORMATS), default="rgbx8888",
        help="named format to request, before any --depth override [rgbx8888]",
    )
    group.add_argument(
        "--native", action="store_true",
        help="send no SetPixelFormat; decode at whatever the server's own ServerInit announced",
    )
    parser.add_argument(
        "--depth", type=int,
        help="override --pixel-format's depth field only, to probe a server's real "
        "narrowing behaviour independent of what it declares",
    )
    parser.add_argument(
        "--encoding", choices=sorted(decoders.ENCODING_NAMES), default="zrle",
        help="encoding to offer the server, forcing it off Raw [zrle]",
    )
    parser.add_argument("--out", default="probe.png", help="screenshot path [probe.png]")
    parser.add_argument(
        "--timeout", type=float,
        help="seconds [the server's own default; an OS-hosted one is slower than a container]",
    )
    args = parser.parse_args()

    server = SERVERS_BY_NAME[args.server]
    requested = None
    if not args.native:
        requested = PIXEL_FORMATS[args.pixel_format]
        if args.depth is not None:
            requested = dataclasses.replace(requested, depth=args.depth)

    class ProbeFactory(VNCDoToolFactory):
        pixel_format = requested
        encodings = [decoders.ENCODING_NAMES[args.encoding]]

    print(f"requesting {requested if requested else '(native)'}")
    client = api.connect(
        f"{HOST}::{server.port}", server.password,
        factory_class=ProbeFactory, username=server.username,
    )
    try:
        client.timeout = args.timeout if args.timeout is not None else server.timeout
        time.sleep(CONNECT_SETTLE)
        client.captureScreen(args.out)
    except Exception as exc:  # noqa: BLE001 -- diagnostic tool, any failure is the result
        print(f"DECODE FAILED: {exc!r}", file=sys.stderr)
        return 1
    else:
        print(f"decoded OK -> {args.out}")
        return 0
    finally:
        client.disconnect()
        api.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
