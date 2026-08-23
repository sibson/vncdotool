"""An encoding sends less than Raw on the content it is designed for.

Bytes on the wire, measured through vnclog rather than estimated. Render time
is the other half and is not measured here: a shared CI runner cannot time a
decode against a 256x192 scene to any useful precision. `make bench` against a
captured fixture does that.
"""
from __future__ import annotations

import select
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import TestCase

from tests.goldens import scenes

from .utils import HOST, TIGERVNC, VNCLOG, port_open, run_vncdo

PROXY_PORT = 5998
PROXY_STARTUP_DEADLINE = 10.0
CAPTURE_DEADLINE = 60.0

# Solid fills and flat regions, which is what these encodings exist for, and
# what a desktop mostly is.
SCENE = "s"


class TestBandwidth(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")
        # The scene the sizes are compared over has to be on screen before
        # each measurement starts, or the first capture pays for the repaint.
        run_vncdo(TIGERVNC, "key", SCENE, "pause", "0.3")

    def _bytes_from_server(self, encodings: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / f"{encodings}.zip"
            proxy = subprocess.Popen(
                [VNCLOG, "-s", f"{HOST}::{TIGERVNC.port}", "--listen", str(PROXY_PORT),
                 "--capture-raw", str(archive)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
            )
            deadline = time.monotonic() + PROXY_STARTUP_DEADLINE
            ready = False
            while time.monotonic() < deadline and not ready:
                if proxy.poll() is not None:
                    break
                rlist, _, _ = select.select([proxy.stderr], [], [], 0.2)
                if rlist and "accepting connections" in proxy.stderr.readline():
                    ready = True
            if not ready:
                proxy.kill()
                proxy.wait(timeout=PROXY_STARTUP_DEADLINE)
                self.fail(f"vnclog never listened on {PROXY_PORT}")

            proxied = TIGERVNC._replace(port=PROXY_PORT)
            # A server sends pixels only when asked (RFC 6143 7.5.3), and
            # of vncdo's commands only capture and expect ask.
            result = run_vncdo(
                proxied, "--encodings", encodings, "capture", str(Path(tmp) / "screen.png")
            )
            proxy.wait(timeout=CAPTURE_DEADLINE)
            if result.returncode != 0:
                self.fail(f"vncdo --encodings {encodings} failed: {result.stderr}")

            with zipfile.ZipFile(archive) as zipped:
                return len(zipped.read("s2c.bin"))

    def test_hextile_sends_less_than_raw(self) -> None:
        raw = self._bytes_from_server("raw")
        hextile = self._bytes_from_server("hextile")
        pixels = scenes.SIZE[0] * scenes.SIZE[1]
        # A capture that never asked for pixels is a few hundred bytes of
        # handshake, and two of those compare equal for the wrong reason.
        self.assertGreater(raw, pixels, f"raw sent {raw} bytes for {pixels} pixels; nothing was captured")
        self.assertLess(
            hextile, raw,
            f"hextile sent {hextile} bytes against raw's {raw} for scene {SCENE!r} "
            f"at {scenes.SIZE[0]}x{scenes.SIZE[1]}",
        )
