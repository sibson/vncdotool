"""Functional tests against the Docker Compose VNC server fleet.

See tests/servers/docker-compose.yml and tests/servers/fleet.mk. The fleet
servers are expected to already be running (e.g. via ``make servers-up``)
before this module executes; a server whose port isn't open is skipped with
a clear message rather than failing the whole run, so this module is also
safe to run outside of that make target.
"""

import socket
import tempfile
from typing import NamedTuple, Optional
from unittest import TestCase

from vncdotool import api

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0


class FleetServer(NamedTuple):
    name: str
    port: int
    password: Optional[str]


# (name, port, password) for each service in tests/servers/docker-compose.yml
FLEET_SERVERS = [
    FleetServer("tigervnc", 5931, None),
    FleetServer("tigervnc-auth", 5932, "vncdotool"),
    FleetServer("x11vnc", 5933, None),
]

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _port_open(host: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _FleetServerTestMixin:
    """Shared test body, parameterized per-server by _make_fleet_test_case below.

    Deliberately does NOT subclass TestCase: only the dynamically generated
    per-server classes below should (otherwise `unittest discover` also
    collects this shared base as its own, serverless test case).
    """

    server: FleetServer

    def setUp(self) -> None:
        if not _port_open(HOST, self.server.port):
            self.skipTest(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                "start the fleet first with `make servers-up`"
            )

    def test_connect_key_and_capture(self) -> None:
        address = f"{HOST}::{self.server.port}"
        with api.connect(address, password=self.server.password) as client:
            client.timeout = CONNECT_TIMEOUT
            client.keyPress("x")

            with tempfile.NamedTemporaryFile(prefix="fleet_", suffix=".png") as png:
                client.captureScreen(png.name)
                data = png.read()

        self.assertTrue(data, f"{self.server.name}: captured screenshot is empty")
        self.assertEqual(
            data[:8],
            PNG_MAGIC,
            f"{self.server.name}: captured file is not a valid PNG",
        )


def _make_fleet_test_case(server: FleetServer) -> type:
    class_name = "TestFleet_" + server.name.replace("-", "_")
    return type(class_name, (_FleetServerTestMixin, TestCase), {"server": server})


# Register one TestCase subclass per fleet server so `unittest discover`
# reports pass/fail/skip separately for each server.
for _server in FLEET_SERVERS:
    _test_case = _make_fleet_test_case(_server)
    globals()[_test_case.__name__] = _test_case
del _server, _test_case


def tearDownModule() -> None:
    # api.connect() starts a background Twisted reactor thread that
    # outlives any individual client connection. Without stopping it here,
    # the interpreter (and `unittest discover`) hangs on exit after all
    # tests in this module have finished.
    api.shutdown()
