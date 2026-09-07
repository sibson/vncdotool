"""ws:// and wss:// against every WebSocket server the fleet can host.

Four independent implementations of the handshake -- websockify (noVNC's
proxy), QEMU's built-in server, Selenoid's Go bridge and KasmVNC -- which
disagree about it, so one server is no evidence about the rest.
"""
from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional
from unittest import TestCase

from PIL import Image, ImageChops

from .utils import (
    HOST,
    QEMU_TLS,
    QEMU_TLS_CA,
    SELENOID,
    TIGERVNC,
    WEBSOCKET_SERVERS,
    WEBSOCKIFY,
    WEBSOCKIFY_TLS,
    VNCServer,
    distinct_colours,
    port_open,
    run_vncdo,
    selenoid_session,
)

# The same TigerVNC instance the TCP tests reach, so a capture through the
# proxy can be held against one taken directly.
PROXIES_TIGERVNC = {WEBSOCKIFY, WEBSOCKIFY_TLS}


class WebSocketTests:
    """Test body every server runs.

    Not a TestCase itself, so the loader reaches it only through the
    subclasses load_tests builds.
    """

    server: VNCServer

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.fail(
                f"{self.server.name} is not listening on {self.server.port};"
                f" {self.server.how_to_start}"
            )
        if self.server is SELENOID:
            session = selenoid_session()
            session.__enter__()
            self.addCleanup(session.__exit__, None, None, None)

    def env(self) -> Optional[Dict[str, str]]:
        if not self.server.address.startswith("wss://"):
            return None
        # SSL_CERT_FILE is how OpenSSL, and so Twisted's platform trust, is
        # pointed at a private CA. There is no vncdotool option that skips
        # verification.
        if self.server is QEMU_TLS:
            if not QEMU_TLS_CA.exists():
                self.fail(f"{self.server.name} has not written {QEMU_TLS_CA}")
            return {"SSL_CERT_FILE": str(QEMU_TLS_CA)}
        certificate = ssl.get_server_certificate((HOST, self.server.port))
        path = Path(tempfile.mkdtemp()) / f"{self.server.name}.pem"
        path.write_text(certificate)
        self.addCleanup(path.unlink)
        return {"SSL_CERT_FILE": str(path)}

    def run_ok(self, *args: str) -> str:
        result = run_vncdo(self.server, *args, env=self.env())
        self.assertEqual(
            result.returncode, 0,
            f"{self.server.name}: vncdo exited {result.returncode}, stderr:\n{result.stderr}",
        )
        return result.stdout + result.stderr

    def test_captures_a_real_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "ws.png"
            self.run_ok("capture", str(shot))
            captured = Image.open(shot).convert("RGB").copy()

        self.assertEqual(captured.size, self.server.size)
        self.assertNotEqual(
            distinct_colours(captured), 1,
            f"{self.server.name}: captured a blank screen",
        )


class QueryStringTests(WebSocketTests):

    def test_verbose_logging_hides_the_query_string(self) -> None:
        """A query string is where Selenoid puts the password."""
        self.assertNotIn("password=vncdotool", self.run_ok("-v", "-v", "pause", "0"))


class ProxiedWebSocketTests(WebSocketTests):

    def test_capture_matches_the_same_server_over_tcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            through_socket = Path(tmp) / "ws.png"
            direct = Path(tmp) / "tcp.png"
            self.run_ok("capture", str(through_socket))
            self.assertEqual(run_vncdo(TIGERVNC, "capture", str(direct)).returncode, 0)

            over_websocket = Image.open(through_socket).convert("RGB").copy()
            over_tcp = Image.open(direct).convert("RGB").copy()

        self.assertIsNone(ImageChops.difference(over_websocket, over_tcp).getbbox())


class TLSWebSocketTests(WebSocketTests):

    def test_untrusted_certificate_is_refused(self) -> None:
        result = run_vncdo(self.server, "pause", "0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("certificate verify failed", result.stderr)


def _bases(server: VNCServer) -> tuple:
    bases = []
    if server in PROXIES_TIGERVNC:
        bases.append(ProxiedWebSocketTests)
    if server.address.startswith("wss://"):
        bases.append(TLSWebSocketTests)
    if "?" in server.address:
        bases.append(QueryStringTests)
    bases.append(WebSocketTests)
    bases.append(TestCase)
    return tuple(bases)


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for server in WEBSOCKET_SERVERS:
        name = f"TestWebSocket_{server.name.replace('-', '_')}"
        case = type(name, _bases(server), {"server": server})
        case.__module__ = __name__
        globals()[name] = case
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite
