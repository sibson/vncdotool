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
import time
from pathlib import Path
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Tuple
from unittest import TestCase

from vncdotool import api

try:
    from .scenarios import SCENARIOS, Scenario, ScenarioContext
except ImportError:
    # capture_screenshots.py runs this module as a plain top-level script
    # (it puts this directory on sys.path itself) rather than importing it
    # as part of the tests.functional package, so the relative import above
    # fails there; fall back to an absolute one against the same sys.path.
    from scenarios import SCENARIOS, Scenario, ScenarioContext  # type: ignore[no-redef]

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0
RETRY_DELAY = 2.0
# Readiness budget for wait_until_ready(): how long one connection attempt
# is given before it is abandoned, and how long to keep making them.
READY_ATTEMPT_TIMEOUT = 20.0
READY_DEADLINE = 180.0

DEFAULT_SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "servers" / "screenshots"


class VNCServer(NamedTuple):
    """What a server is and what it can do.

    ``capabilities`` (see below) is the one obvious place a server declares
    what it can do; scenarios (tests/functional/scenarios.py) declare what
    they ``require`` and a server missing a capability skips rather than
    running a test that can't mean anything for it. ``size`` and
    ``renders_desktop`` stay as plain fields because a scenario body needs
    the actual values, not just a yes/no -- ``capabilities`` is derived from
    them rather than duplicating them.
    """

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
    # Whether the desktop visibly changes in a *known region* in response
    # to input. Deferred; see "input-reactive test surface" in
    # docs/server-compatibility-plan.md.
    input_reactive: bool = False
    # How long to wait for the server to answer a single request. The
    # default suits a container on loopback; an OS-hosted server sharing a
    # busy machine's real desktop can be far slower.
    timeout: float = CONNECT_TIMEOUT
    # How to get this server running, quoted when a test skips itself.
    how_to_start: str = "start the servers first with `make servers-up`"

    @property
    def auth_capability(self) -> str:
        """The ``auth:*`` capability this server's credentials negotiate."""
        if self.username is not None:
            return "auth:ard"
        if self.password is not None:
            return "auth:vncpass"
        return "auth:none"

    @property
    def capabilities(self) -> FrozenSet[str]:
        """What this server can do, as the set scenarios match ``requires`` against."""
        caps = {self.auth_capability}
        if self.size is not None:
            caps.add("known_size")
        if self.renders_desktop:
            caps.add("renders_desktop")
        if self.input_reactive:
            caps.add("input_reactive")
        return frozenset(caps)


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


def scenario_artifact_dir(server: VNCServer, scenario_name: str) -> Path:
    """Where one server's one scenario writes its artifacts, created if needed."""
    path = screenshot_dir() / server.name / scenario_name
    path.mkdir(parents=True, exist_ok=True)
    return path


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by register_server_tests().

    Deliberately does NOT subclass TestCase: only the generated per-server
    classes should (otherwise `unittest discover` also collects this shared
    base as its own, serverless test case).

    register_server_tests() adds one `test_<scenario.name>` method per
    scenario on top of this mixin -- see _make_scenario_test() below -- so
    this class only carries what every one of those methods needs: the
    server-reachability skip shared by all of them.
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.skipTest(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )


def _make_scenario_test(scenario: Scenario) -> object:
    """Build one `test_<scenario.name>` method bound to `scenario`.

    A missing required capability is a `skipTest` naming the capability,
    never a silent pass -- that distinction is what keeps a skip from
    reading as coverage in the compatibility matrix (e.g. macOS Screen
    Sharing's black framebuffer must not read as green).
    """

    def test_scenario(self: _VNCServerTestMixin) -> None:
        missing = scenario.requires - self.server.capabilities
        if missing:
            self.skipTest(
                f"{self.server.name} does not support required capabilit"
                f"{'y' if len(missing) == 1 else 'ies'} {sorted(missing)} "
                f"for scenario {scenario.name!r}"
            )

        artifact_dir = scenario_artifact_dir(self.server, scenario.name)
        ctx = ScenarioContext(server=self.server, artifact_dir=artifact_dir)
        with connect(self.server) as client:
            scenario.run(client, ctx)

    test_scenario.__name__ = f"test_{scenario.name}"
    test_scenario.__doc__ = scenario.description
    return test_scenario


def register_server_tests(servers: List[VNCServer], namespace: Dict[str, object]) -> None:
    """Add one TestCase subclass per server to a test module's namespace.

    Each subclass gets one `test_<scenario>` method per entry in
    `scenarios.SCENARIOS`, so `unittest discover` reports a separate
    pass/fail/skip per server *and* per scenario (e.g.
    `TestServer_tigervnc.test_capture`) instead of one test per server that
    stops at the first thing that misbehaves.
    """
    for server in servers:
        name = "TestServer_" + server.name.replace("-", "_")
        attrs: Dict[str, object] = {
            "server": server,
            # __module__ so test ids name the module that registered the
            # case rather than this one.
            "__module__": namespace.get("__name__", __name__),
        }
        for scenario in SCENARIOS:
            attrs[f"test_{scenario.name}"] = _make_scenario_test(scenario)
        namespace[name] = type(name, (_VNCServerTestMixin, TestCase), attrs)
