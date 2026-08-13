"""Functional tests against the Docker Compose VNC test servers.

See tests/servers/docker-compose.yml and tests/servers/servers.mk. The test
servers are expected to already be running (e.g. via ``make servers-up``)
before this module executes; a server whose port isn't open is skipped with
a clear message rather than failing the whole run, so this module is also
safe to run outside of that make target.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

import os
import socket
from pathlib import Path
from typing import NamedTuple, Optional, Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import api

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0

DEFAULT_SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "servers" / "screenshots"


class VNCServer(NamedTuple):
    name: str
    port: int
    password: Optional[str]
    # Screen size the server's entrypoint configures, so a capture can be
    # checked against what the server said it was serving.
    size: Tuple[int, int] = (1024, 768)


# (name, port, password) for each service in tests/servers/docker-compose.yml
VNC_SERVERS = [
    VNCServer("tigervnc", 5931, None),
    VNCServer("tigervnc-auth", 5932, "vncdotool"),
    VNCServer("x11vnc", 5933, None),
]

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# getcolors() returns None above this many distinct colours, which is itself
# proof the capture isn't a flat colour, so the cap only needs to be cheap.
MAX_COLOURS = 256


def screenshot_dir() -> Path:
    """Directory screenshots are written to, created if needed."""
    path = Path(os.environ.get("VNCDOTOOL_SCREENSHOT_DIR", DEFAULT_SCREENSHOT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def port_open(host: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by _make_server_test_case below.

    Deliberately does NOT subclass TestCase: only the dynamically generated
    per-server classes below should (otherwise `unittest discover` also
    collects this shared base as its own, serverless test case).
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.skipTest(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                "start the servers first with `make servers-up`"
            )

    def test_connect_key_and_capture(self) -> None:
        """End-to-end round trip against one real server.

        Passing means, in order:

        * the RFB handshake completed against this server's protocol version
          and security type (None, or VNC password auth for tigervnc-auth);
        * a key event was accepted without the server dropping the session;
        * a framebuffer update was received and encoded to a PNG file;
        * that PNG is the size the server's entrypoint configured, and is not
          a single flat colour -- i.e. we decoded real screen content
          (the entrypoints run xlogo for exactly this reason) rather than
          the all-black framebuffer you get when updates never arrive.
        """
        address = f"{HOST}::{self.server.port}"
        png = screenshot_dir() / f"{self.server.name}.png"

        with api.connect(address, password=self.server.password) as client:
            client.timeout = CONNECT_TIMEOUT
            client.keyPress("x")
            client.captureScreen(str(png))

        data = png.read_bytes()
        print(f"{self.server.name}: screenshot written to {png}")

        self.assertTrue(data, f"{self.server.name}: captured screenshot is empty")
        self.assertEqual(
            data[:8],
            PNG_MAGIC,
            f"{self.server.name}: captured file is not a valid PNG",
        )

        with Image.open(png) as image:
            self.assertEqual(
                image.size,
                self.server.size,
                f"{self.server.name}: capture is not the size the server serves",
            )
            colours = image.convert("RGB").getcolors(maxcolors=MAX_COLOURS)

        self.assertNotEqual(
            colours if colours is None else len(colours),
            1,
            f"{self.server.name}: capture is a single flat colour, "
            "no screen content was decoded",
        )


def _make_server_test_case(server: VNCServer) -> type:
    class_name = "TestServer_" + server.name.replace("-", "_")
    return type(class_name, (_VNCServerTestMixin, TestCase), {"server": server})


# Register one TestCase subclass per test server so `unittest discover`
# reports pass/fail/skip separately for each server.
for _server in VNC_SERVERS:
    _test_case = _make_server_test_case(_server)
    globals()[_test_case.__name__] = _test_case
del _server, _test_case


def tearDownModule() -> None:
    # api.connect() starts a background Twisted reactor thread that
    # outlives any individual client connection. Without stopping it here,
    # the interpreter (and `unittest discover`) hangs on exit after all
    # tests in this module have finished.
    api.shutdown()
