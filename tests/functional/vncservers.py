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

# Named by full path rather than resolved through PATH: another working tree's
# .venv can come first there, and the suite would report its behaviour as this
# branch's.
_SCRIPTS = Path(sys.executable).parent
_EXE_SUFFIX = ".exe" if os.name == "nt" else ""
VNCDO = str(_SCRIPTS / f"vncdo{_EXE_SUFFIX}")
VNCDO_REPLAY = str(_SCRIPTS / f"vncdo-replay{_EXE_SUFFIX}")
VNCLOG = str(_SCRIPTS / f"vnclog{_EXE_SUFFIX}")
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
    # False means a flat, usually all-black, framebuffer is expected rather
    # than a failure -- see the macOS note in tests/servers/screen-sharing.
    renders_desktop: bool = True
    # The default suits a container on loopback; an OS-hosted server sharing
    # a busy machine's real desktop can be far slower.
    timeout: float = CONNECT_TIMEOUT
    # How to get this server running, quoted when a test fails because it is down.
    how_to_start: str = "start the servers first with `make servers-up`"


# One constant per service in tests/servers/docker-compose.yml, named so a
# test that needs a specific one can import it directly instead of
# searching DOCKER_SERVERS by name.
TIGERVNC = VNCServer("tigervnc", 5931)
TIGERVNC_AUTH = VNCServer("tigervnc-auth", 5932, password="vncdotool")
X11VNC = VNCServer("x11vnc", 5933)
# 800x600 is the demo's hard-coded size; it takes no -geometry option.
LIBVNCSERVER_EXAMPLE = VNCServer("libvncserver-example", 5935, size=(800, 600))
# Small framebuffer, for golden capture; see specs/decoder-goldens.md.
TIGERVNC_GOLDEN = VNCServer("tigervnc-golden", 5936, size=(256, 192))

DOCKER_SERVERS = [TIGERVNC, TIGERVNC_AUTH, X11VNC, LIBVNCSERVER_EXAMPLE, TIGERVNC_GOLDEN]

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

OS_SERVERS_BY_PLATFORM: Dict[str, List[VNCServer]] = {
    "win32": [ULTRAVNC],
    "darwin": [SCREEN_SHARING],
}


def os_servers(platform: str = sys.platform) -> List[VNCServer]:
    return OS_SERVERS_BY_PLATFORM.get(platform, [])


def select_servers(group: str) -> List[VNCServer]:
    groups = {"docker": DOCKER_SERVERS, "os": os_servers()}
    if group == "all":
        return [server for servers in groups.values() for server in servers]
    if group not in groups:
        raise ValueError(f"unknown server group {group!r}, expected one of {sorted(groups)} or 'all'")
    return groups[group]


def screenshot_dir() -> Path:
    path = Path(os.environ.get("VNCDOTOOL_SCREENSHOT_DIR", DEFAULT_SCREENSHOT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def port_open(host: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    """Cheap liveness check, not readiness -- see wait_until_ready()."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def connect(server: VNCServer, timeout: Optional[float] = None) -> api.ThreadedVNCClientProxy:
    """Connect to one server, with whatever credentials its security type needs.

    Remember that the returned client is a context manager, and that
    ``api.shutdown()`` still has to be called once before the process exits.
    And that shutdown is terminal for the whole process: after it, no
    further ``connect()`` can ever work again (the reactor cannot restart),
    which is why only ONE test module -- test_api_lifecycle.py -- may use
    this in-process; everything else shells out via run_vncdo().
    """
    client = api.connect(
        f"{HOST}::{server.port}",
        password=server.password,
        username=server.username,
    )
    client.timeout = server.timeout if timeout is None else timeout
    return client


def capture_screenshot(server: VNCServer, path: Path, timeout: Optional[float] = None) -> Path:
    with connect(server, timeout=timeout) as client:
        client.captureScreen(str(path))
    return path


def distinct_colours(image: Image.Image) -> Optional[int]:
    colours = image.convert("RGB").getcolors(maxcolors=MAX_COLOURS)
    return colours if colours is None else len(colours)


def has_expected_content(server: VNCServer, colours: Optional[int]) -> bool:
    if not server.renders_desktop:
        return True
    return colours != 1


def wait_until_ready(
    server: VNCServer,
    deadline_seconds: float = READY_DEADLINE,
    attempt_timeout: float = READY_ATTEMPT_TIMEOUT,
) -> bool:
    """Block until ``server`` serves the screen the tests expect, or give up.

    Servers accept connections before they have anything to show, so
    readiness has to be a capture. The whole connection is retried because
    macOS Screen Sharing is socket-activated: the first connection starts
    it and can stall indefinitely while the next succeeds at once.
    """
    deadline = time.monotonic() + deadline_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if not port_open(HOST, server.port):
            time.sleep(RETRY_DELAY)
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                probe = Path(tmp) / f"{server.name}-ready.png"
                capture_screenshot(server, probe, timeout=attempt_timeout)
                with Image.open(probe) as image:
                    colours = distinct_colours(image)
        except Exception as exc:  # noqa: BLE001 - any failure means try again
            print(f"{server.name}: not ready yet (attempt {attempt}: {exc})")
            continue
        if not has_expected_content(server, colours):
            print(f"{server.name}: not ready yet (attempt {attempt}: capture is flat)")
            time.sleep(RETRY_DELAY)
            continue
        print(f"{server.name}: ready after {attempt} attempt(s)")
        return True

    print(f"{server.name}: never served the content it is expected to render")
    return False


def assert_cli_installed() -> None:
    missing = [script for script in (VNCDO, VNCDO_REPLAY, VNCLOG) if not Path(script).exists()]
    if missing:
        raise AssertionError(
            f"{', '.join(missing)} missing. These are console_scripts entry points: run "
            "`uv sync` in this working tree, or `pip install -e .` into the environment "
            "running these tests."
        )


assert_cli_installed()


def vncdo_argv(server: VNCServer, *args: str) -> List[str]:
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


def _terminate(process: subprocess.Popen, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def start_replay_server(
    testcase: TestCase, archive: Path, port: int, deadline: float = 10.0
) -> subprocess.Popen:
    """Start `vncdo-replay --server ARCHIVE --listen PORT --forever`, cleanup registered.

    Fails fast, with its stderr, if the process exits before listening."""
    server = subprocess.Popen(
        [VNCDO_REPLAY, "--server", str(archive), "--listen", str(port), "--forever"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    # Not kill(): Twisted's SIGTERM handler stops the reactor, so the
    # process exits through atexit and flushes what it still owes.
    testcase.addCleanup(_terminate, server)
    testcase.addCleanup(server.stdout.close)
    testcase.addCleanup(server.stderr.close)

    deadline_at = time.monotonic() + deadline
    while time.monotonic() < deadline_at:
        if server.poll() is not None:
            testcase.fail(f"vncdo-replay --server exited before listening; stderr:\n{server.stderr.read()}")
        if port_open(HOST, port):
            return server
        time.sleep(0.2)
    server.kill()
    testcase.fail(f"vncdo-replay --server never listened on {port}: {server.communicate()[1]}")


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by register_server_tests().

    Deliberately does NOT subclass TestCase, or `unittest discover` would
    also collect this shared base as its own, serverless test case.
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.fail(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )

    def run_vncdo_ok(self, *args: str) -> subprocess.CompletedProcess:
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
            distinct = distinct_colours(image)

        if not self.server.renders_desktop:
            print(
                f"{self.server.name}: {distinct} colours captured; content is not "
                "asserted, this server has no rendered desktop behind it"
            )
            return

        self.assertTrue(
            has_expected_content(self.server, distinct),
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
