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
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import api

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0
RETRY_DELAY = 2.0
# Readiness budget for wait_until_ready(): how long one connection attempt
# is given before it is abandoned, and how long to keep making them.
READY_ATTEMPT_TIMEOUT = 20.0
READY_DEADLINE = 180.0

# A console_scripts entry point, so only on PATH once vncdotool is installed.
VNCDO = "vncdo"
REPO_ROOT = Path(__file__).resolve().parents[2]
# Added to the server's response budget for interpreter start-up and handshake.
SUBPROCESS_TIMEOUT_HEADROOM = 10.0

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
    # How long to wait for the server to answer a single request. The
    # default suits a container on loopback; an OS-hosted server sharing a
    # busy machine's real desktop can be far slower.
    timeout: float = CONNECT_TIMEOUT
    # How to get this server running, quoted when a test skips itself.
    how_to_start: str = "start the servers first with `make servers-up`"


# One entry per service in tests/servers/docker-compose.yml.
DOCKER_SERVERS = [
    VNCServer("tigervnc", 5931),
    VNCServer("tigervnc-auth", 5932, password="vncdotool"),
    VNCServer("x11vnc", 5933),
    # 800x600 is the demo's hard-coded size; it takes no -geometry option.
    VNCServer("libvncserver-example", 5935, size=(800, 600)),
]

# An event sink rather than a rendering server, so it stays out of the smoke
# grid; test_events.py still needs its host/port.
VNCEV = VNCServer("vncev", 5934, renders_desktop=False, size=None)

# Credentials the OS-hosted server setup scripts configure. They are spike
# credentials for a throwaway runner, deliberately visible; a permanent job
# passes real ones through these environment variables from CI secrets.
OS_SERVER_USERNAME = os.environ.get("VNCDOTOOL_OS_SERVER_USERNAME", "vncspike")
OS_SERVER_PASSWORD = os.environ.get("VNCDOTOOL_OS_SERVER_PASSWORD", "vncspike1")
OS_SERVER_PORT = int(os.environ.get("VNCDOTOOL_OS_SERVER_PORT", "5900"))
# An OS-hosted server shares a real, sometimes busy, desktop session, and
# answers input events a lot less promptly than a container does: macOS
# Screen Sharing took over five seconds to acknowledge a key event.
OS_SERVER_TIMEOUT = float(os.environ.get("VNCDOTOOL_OS_SERVER_TIMEOUT", "60"))

ULTRAVNC = VNCServer(
    name="ultravnc",
    port=OS_SERVER_PORT,
    password=OS_SERVER_PASSWORD,
    # The Windows runner's own desktop resolution, not one we configure.
    size=None,
    timeout=OS_SERVER_TIMEOUT,
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
    timeout=OS_SERVER_TIMEOUT,
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


def connect(server: VNCServer, timeout: Optional[float] = None) -> api.ThreadedVNCClientProxy:
    """Connect to one server, with whatever credentials its security type needs.

    Remember that the returned client is a context manager, and that
    ``api.shutdown()`` still has to be called once before the process exits.
    """
    client = api.connect(
        f"{HOST}::{server.port}",
        password=server.password,
        username=server.username,
    )
    client.timeout = server.timeout if timeout is None else timeout
    return client


def capture_screenshot(server: VNCServer, path: Path, timeout: Optional[float] = None) -> Path:
    """Capture ``server``'s framebuffer to ``path`` as a PNG."""
    with connect(server, timeout=timeout) as client:
        client.captureScreen(str(path))
    return path


def wait_until_ready(
    server: VNCServer,
    deadline_seconds: float = READY_DEADLINE,
    attempt_timeout: float = READY_ATTEMPT_TIMEOUT,
) -> bool:
    """Block until ``server`` completes a whole RFB round trip, or give up.

    An open port is not readiness. The Docker servers need a drawn-content
    marker on top of it (tests/servers/draw-content.sh); an OS-hosted
    server needs this instead, because the first connection can stall
    indefinitely while the next one succeeds at once -- macOS Screen
    Sharing is socket-activated, so that first connection is also what
    starts the server.

    Retrying a whole connection is therefore the only probe that means
    anything: a per-request timeout can't rescue a connection that never
    finished its handshake.
    """
    deadline = time.monotonic() + deadline_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if not port_open(HOST, server.port):
            time.sleep(RETRY_DELAY)
            continue
        try:
            with connect(server, timeout=attempt_timeout) as client:
                client.refreshScreen()
        except Exception as exc:  # noqa: BLE001 - any failure means try again
            print(f"{server.name}: not ready yet (attempt {attempt}: {exc})")
            continue
        print(f"{server.name}: ready after {attempt} attempt(s)")
        return True

    print(f"{server.name}: never completed an RFB round trip")
    return False


def assert_cli_under_test() -> None:
    """Fail unless the `vncdo` these tests shell out to is this checkout.

    Nothing else notices: the suite passes against another copy of
    vncdotool and reports its behaviour as this branch's.
    """
    on_path = shutil.which(VNCDO)
    if on_path is None:
        raise AssertionError(
            f"`{VNCDO}` is not on PATH. It is a console_scripts entry point, so run "
            "`make venv` in this working tree, or `pip install -e .` into the "
            "environment running these tests."
        )

    # Running from the working tree puts it on sys.path, so what this
    # process imports says nothing about what the console script will.
    try:
        shebang = Path(on_path).read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return  # not a script we can read, e.g. a Windows .exe wrapper
    if not shebang.startswith("#!"):
        return
    interpreter = shebang[2:].strip()

    with tempfile.TemporaryDirectory() as neutral:
        found = subprocess.run(
            [interpreter, "-c", "import vncdotool; print(vncdotool.__file__)"],
            capture_output=True, text=True, cwd=neutral, timeout=60,
        )
    if found.returncode != 0:
        raise AssertionError(f"`{VNCDO}`'s interpreter cannot import vncdotool:\n{found.stderr}")

    installed = Path(found.stdout.strip()).resolve()
    if REPO_ROOT not in installed.parents:
        raise AssertionError(
            f"`{VNCDO}` on PATH ({on_path}) imports vncdotool from {installed}, not this "
            f"checkout at {REPO_ROOT}. These tests shell out to it, so they would report "
            "that copy's behaviour as this branch's. Run `make venv` in this working tree "
            "(and do not symlink another one's .venv -- its editable install still points "
            "where it was created)."
        )


assert_cli_under_test()


def vncdo_argv(server: VNCServer, *args: str) -> List[str]:
    """Build a `vncdo` argv for `server`, with whatever auth its security type needs."""
    argv = [VNCDO, "-s", f"{HOST}::{server.port}"]
    if server.password is not None:
        argv += ["-p", server.password]
    if server.username is not None:
        argv += ["-u", server.username]
    argv.extend(args)
    return argv


def run_vncdo(
    server: VNCServer, *args: str, timeout: Optional[float] = None
) -> subprocess.CompletedProcess:
    """Run the real `vncdo` CLI against `server` and return the completed process.

    Never api.connect(): a hang is then contained by the kernel reaping the
    subprocess at `timeout`, not by anything in-process.
    """
    argv = vncdo_argv(server, *args)
    budget = (server.timeout if timeout is None else timeout) + SUBPROCESS_TIMEOUT_HEADROOM
    try:
        # stdin closed so an unexpected getpass() prompt fails instead of blocking.
        return subprocess.run(argv, capture_output=True, text=True, timeout=budget, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"{server.name}: `{' '.join(argv)}` did not finish within {budget}s"
        ) from exc
    except FileNotFoundError as exc:
        raise AssertionError(
            f"{server.name}: `{VNCDO}` not found on PATH -- install vncdotool "
            "(`pip install -e .`) so its console script is available"
        ) from exc


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by register_server_tests().

    Deliberately does NOT subclass TestCase, or `unittest discover` would
    also collect this shared base as its own, serverless test case.
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.skipTest(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )

    def run_vncdo_ok(self, *args: str) -> subprocess.CompletedProcess:
        """run_vncdo(), asserting the CLI actually succeeded."""
        result = run_vncdo(self.server, *args)
        self.assertEqual(
            result.returncode,
            0,
            f"{self.server.name}: `vncdo {' '.join(args)}` exited "
            f"{result.returncode}, stderr:\n{result.stderr}",
        )
        return result

    def test_connect(self) -> None:
        """Handshake and auth succeed: `pause 0` still needs a live connection."""
        self.run_vncdo_ok("pause", "0")

    def test_keypress(self) -> None:
        """A key event is accepted without the server dropping the session."""
        self.run_vncdo_ok("key", "x")

    def test_mousemove(self) -> None:
        """A pointer event is accepted without the server dropping the session."""
        self.run_vncdo_ok("move", "10", "10")

    def test_capture(self) -> None:
        """A framebuffer update is received and encoded to a PNG.

        A flat colour means no content was decoded, so it fails for any
        server with a desktop rendered behind it.
        """
        png = screenshot_dir() / f"{self.server.name}.png"

        self.run_vncdo_ok("capture", str(png))

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
            # __module__ so test ids name the registering module, not this one.
            {"server": server, "__module__": namespace.get("__name__", __name__)},
        )
