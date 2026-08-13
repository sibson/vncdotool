"""Shared description of the VNC servers vncdotool is tested against.

Two families of server are described here and driven by the same code:

* ``docker`` -- the Linux servers built and run by
  ``tests/servers/docker-compose.yml`` (see ``make servers-up``);
* ``os`` -- an OS-hosted server on the machine running the tests, i.e.
  UltraVNC on Windows or Apple Screen Sharing on macOS, set up by the
  scripts under ``tests/servers/ultravnc`` and
  ``tests/servers/screen-sharing``.

The two differ only in how the server is started and in what a capture is
allowed to contain, so everything else -- connecting, capturing, the
per-server test body, the screenshot gallery -- is shared rather than
written twice.
"""

import os
import socket
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import api

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0

DEFAULT_SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "servers" / "screenshots"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# getcolors() returns None above this many distinct colours, which is itself
# proof the capture isn't a flat colour, so the cap only needs to be cheap.
MAX_COLOURS = 256


class VNCServer(NamedTuple):
    name: str
    port: int
    password: Optional[str] = None
    # Username, for servers whose security type authenticates one (Apple's
    # ARD/Diffie-Hellman); None selects VNC password auth or no auth.
    username: Optional[str] = None
    # Screen size the server is known to serve, so a capture can be checked
    # against it; None where the size is whatever the host display happens
    # to be and therefore can't be asserted.
    size: Optional[Tuple[int, int]] = (1024, 768)
    # Whether the server has a rendered desktop behind it. False means a
    # flat, usually all-black, framebuffer is expected rather than a
    # failure -- see the macOS note in tests/servers/screen-sharing.
    renders_desktop: bool = True
    # How to get this server running, quoted when a test skips itself.
    how_to_start: str = "start the servers first with `make servers-up`"


# One entry per service in tests/servers/docker-compose.yml.
DOCKER_SERVERS = [
    VNCServer("tigervnc", 5931),
    VNCServer("tigervnc-auth", 5932, password="vncdotool"),
    VNCServer("x11vnc", 5933),
]

# Credentials the OS-hosted server setup scripts configure. They are spike
# credentials for a throwaway runner, deliberately visible; a permanent job
# passes real ones through these environment variables from CI secrets.
OS_SERVER_USERNAME = os.environ.get("VNCDOTOOL_OS_SERVER_USERNAME", "vncspike")
OS_SERVER_PASSWORD = os.environ.get("VNCDOTOOL_OS_SERVER_PASSWORD", "vncspike1")
OS_SERVER_PORT = int(os.environ.get("VNCDOTOOL_OS_SERVER_PORT", "5900"))

ULTRAVNC = VNCServer(
    name="ultravnc",
    port=OS_SERVER_PORT,
    password=OS_SERVER_PASSWORD,
    # The Windows runner's own desktop resolution, not one we configure.
    size=None,
    how_to_start="set the server up first with tests/servers/ultravnc/setup.ps1",
)

SCREEN_SHARING = VNCServer(
    name="screen-sharing",
    port=OS_SERVER_PORT,
    password=OS_SERVER_PASSWORD,
    # macOS Screen Sharing authenticates a local user over ARD/DH; the
    # legacy VNC-password path is silently accepted but non-functional on
    # current macOS.
    username=OS_SERVER_USERNAME,
    size=None,
    # A hosted macOS runner has no rendered desktop session behind the
    # framebuffer, so captures come back black even though the protocol,
    # auth and input round trip all succeeded.
    renders_desktop=False,
    how_to_start="set the server up first with tests/servers/screen-sharing/setup.sh",
)

# The OS-hosted server for the platform the tests are running on, if any.
OS_SERVERS_BY_PLATFORM: Dict[str, List[VNCServer]] = {
    "win32": [ULTRAVNC],
    "darwin": [SCREEN_SHARING],
}


def os_servers(platform: str = sys.platform) -> List[VNCServer]:
    """OS-hosted servers testable on this platform, empty on other platforms."""
    return OS_SERVERS_BY_PLATFORM.get(platform, [])


def select_servers(group: str) -> List[VNCServer]:
    """Servers in a named group: ``docker``, ``os``, or ``all``."""
    groups = {"docker": DOCKER_SERVERS, "os": os_servers()}
    if group == "all":
        return [server for servers in groups.values() for server in servers]
    if group not in groups:
        raise ValueError(f"unknown server group {group!r}, expected one of {sorted(groups)} or 'all'")
    return groups[group]


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


def connect(server: VNCServer, timeout: float = CONNECT_TIMEOUT) -> api.ThreadedVNCClientProxy:
    """Connect to one server, with whatever credentials its security type needs.

    Remember that the returned client is a context manager, and that
    ``api.shutdown()`` still has to be called once before the process exits.
    """
    client = api.connect(
        f"{HOST}::{server.port}",
        password=server.password,
        username=server.username,
    )
    client.timeout = timeout
    return client


def capture_screenshot(server: VNCServer, path: Path, timeout: float = CONNECT_TIMEOUT) -> Path:
    """Capture ``server``'s framebuffer to ``path`` as a PNG."""
    with connect(server, timeout=timeout) as client:
        client.captureScreen(str(path))
    return path


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by register_server_tests().

    Deliberately does NOT subclass TestCase: only the generated per-server
    classes should (otherwise `unittest discover` also collects this shared
    base as its own, serverless test case).
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.skipTest(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )

    def test_connect_key_and_capture(self) -> None:
        """End-to-end round trip against one real server.

        Passing means, in order:

        * the RFB handshake completed against this server's protocol version
          and security type (none, VNC password, or ARD/Diffie-Hellman);
        * a key event was accepted without the server dropping the session;
        * a framebuffer update was received and encoded to a PNG file;
        * that PNG is the size the server said it serves, and -- for a server
          with a desktop rendered behind it -- is not a single flat colour,
          i.e. we decoded real screen content rather than the all-black
          framebuffer you get when updates never arrive.
        """
        png = screenshot_dir() / f"{self.server.name}.png"

        with connect(self.server) as client:
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
            if self.server.size is not None:
                self.assertEqual(
                    image.size,
                    self.server.size,
                    f"{self.server.name}: capture is not the size the server serves",
                )
            colours = image.convert("RGB").getcolors(maxcolors=MAX_COLOURS)

        distinct = colours if colours is None else len(colours)
        if not self.server.renders_desktop:
            print(
                f"{self.server.name}: {distinct} colours captured; content is not "
                "asserted, this server has no rendered desktop behind it"
            )
            return

        self.assertNotEqual(
            distinct,
            1,
            f"{self.server.name}: capture is a single flat colour, "
            "no screen content was decoded",
        )


def register_server_tests(servers: List[VNCServer], namespace: Dict[str, object]) -> None:
    """Add one TestCase subclass per server to a test module's namespace.

    Gives `unittest discover` a separate pass/fail/skip per server instead of
    one test that stops at the first server that misbehaves.
    """
    for server in servers:
        name = "TestServer_" + server.name.replace("-", "_")
        namespace[name] = type(
            name,
            (_VNCServerTestMixin, TestCase),
            # __module__ so test ids name the module that registered the
            # case rather than this one.
            {"server": server, "__module__": namespace.get("__name__", __name__)},
        )
