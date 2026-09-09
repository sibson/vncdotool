"""What the WebSocket transport does that the compatibility grids cannot see.

What is left for this module is the client's own behaviour: refusing an
unverifiable wss:// certificate, and keeping a password out of the log when
the address carries one. The per-server grid in test_server_compat_docker.py
already drives input and captures against every product here.
"""
from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional

from PIL import Image

from .utils import (
    HOST,
    QEMU_TLS,
    QEMU_TLS_CA,
    SUPPORTED_SERVERS,
    WEBSOCKET_SERVERS,
    FleetTestCase,
    VNCServer,
    distinct_colours,
    run_vncdo,
)


class WebSocketTests:
    """Test body every server runs.

    Not a TestCase itself, so the loader reaches it only through the
    subclasses load_tests builds.
    """

    server: VNCServer

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

    def assert_survives(self, *args: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.run_ok(*args, "pause", "0.3", "capture", str(Path(tmp) / "after.png"))


class BasicWebSocketTests(WebSocketTests):
    def test_a_key_event_is_accepted(self) -> None:
        self.assert_survives("key", "x")

    def test_a_pointer_event_is_accepted(self) -> None:
        self.assert_survives("move", "10", "10")

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


class TLSWebSocketTests(WebSocketTests):

    def test_untrusted_certificate_is_refused(self) -> None:
        result = run_vncdo(self.server, "pause", "0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("certificate verify failed", result.stderr)


def _bases(server: VNCServer) -> tuple:
    bases = []
    if server not in SUPPORTED_SERVERS:
        bases.append(BasicWebSocketTests)
    if server.address.startswith("wss://"):
        bases.append(TLSWebSocketTests)
    if "?" in server.address:
        bases.append(QueryStringTests)
    bases.append(WebSocketTests)
    bases.append(FleetTestCase)
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
