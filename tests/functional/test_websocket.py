"""ws:// and wss:// against websockify, the front end noVNC and Proxmox use.

Both services proxy the same TigerVNC the TCP tests use, so a capture taken
through the WebSocket can be held against one taken directly.
"""
from __future__ import annotations

import ssl
import tempfile
from pathlib import Path
from typing import Dict, Optional
from unittest import TestCase

from PIL import Image, ImageChops

from .utils import (
    HOST,
    TIGERVNC,
    WEBSOCKIFY,
    WEBSOCKIFY_TLS,
    VNCServer,
    distinct_colours,
    port_open,
    run_vncdo,
)


class WebSocketTestCase(TestCase):
    server: VNCServer = WEBSOCKIFY

    def setUp(self) -> None:
        for server in (self.server, TIGERVNC):
            if not port_open(HOST, server.port):
                self.fail(
                    f"{server.name} is not listening on {server.port}; {server.how_to_start}"
                )

    def env(self) -> Optional[Dict[str, str]]:
        return None

    def run_ok(self, *args: str) -> str:
        result = run_vncdo(self.server, *args, env=self.env())
        self.assertEqual(
            result.returncode, 0,
            f"{self.server.name}: vncdo exited {result.returncode}, stderr:\n{result.stderr}",
        )
        return result.stdout + result.stderr

    def test_capture_matches_the_same_server_over_tcp(self) -> None:
        """The URL carries a path and a query string, and the session still works."""
        with tempfile.TemporaryDirectory() as tmp:
            through_socket = Path(tmp) / "ws.png"
            direct = Path(tmp) / "tcp.png"
            self.run_ok("capture", str(through_socket))
            self.assertEqual(run_vncdo(TIGERVNC, "capture", str(direct)).returncode, 0)

            over_websocket = Image.open(through_socket).convert("RGB").copy()
            over_tcp = Image.open(direct).convert("RGB").copy()

        self.assertEqual(over_websocket.size, TIGERVNC.size)
        self.assertNotEqual(distinct_colours(over_websocket), 1)
        self.assertIsNone(ImageChops.difference(over_websocket, over_tcp).getbbox())

    def test_verbose_logging_hides_the_query_string(self) -> None:
        """A query string is where Selenoid puts the password (issue #259)."""
        self.assertNotIn("password=vncdotool", self.run_ok("-v", "-v", "pause", "0"))


class WebSocketTLSTestCase(WebSocketTestCase):
    server = WEBSOCKIFY_TLS

    def env(self) -> Optional[Dict[str, str]]:
        """SSL_CERT_FILE holding the server's own self-signed certificate.

        Which is how OpenSSL, and so Twisted's platform trust, is pointed at a
        private CA -- there is no vncdotool option that skips verification.
        """
        certificate = ssl.get_server_certificate((HOST, self.server.port))
        path = Path(tempfile.mkdtemp()) / "websockify.pem"
        path.write_text(certificate)
        self.addCleanup(path.unlink)
        return {"SSL_CERT_FILE": str(path)}

    def test_untrusted_certificate_is_refused(self) -> None:
        """websockify's certificate is self-signed, so the default trust store rejects it."""
        result = run_vncdo(self.server, "pause", "0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("certificate verify failed", result.stderr)
