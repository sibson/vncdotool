"""An encoding sends less than Raw on the content it is designed for.

Bytes on the wire, measured through vnclog rather than estimated. Render time
is the other half and is not measured here: a shared CI runner cannot time a
decode against a 256x192 scene to any useful precision. `make bench` against a
captured fixture does that.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from tests.goldens import scenes

from .utils import HOST, TIGERVNC, capture_through_vnclog, port_open, run_vncdo

PROXY_PORT = 5998

FLAT = "s"
DENSE = "d"


class TestBandwidth(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")

    def _show(self, scene: str) -> None:
        # The scene the sizes are compared over has to be on screen before
        # each measurement starts, or the first capture pays for the repaint.
        run_vncdo(TIGERVNC, "key", scene, "pause", "0.3")

    def _bytes_from_server(self, encodings: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            # A server sends pixels only when asked (RFC 6143 7.5.3), and of
            # vncdo's commands only capture and expect ask.
            recorded = capture_through_vnclog(
                self, TIGERVNC, PROXY_PORT,
                "--encodings", encodings, "capture", str(Path(tmp) / "screen.png"),
            )
        return len(recorded.s2c)

    def _assert_sends_less_than_raw(self, encoding: str, scene: str) -> None:
        self._show(scene)
        raw = self._bytes_from_server("raw")
        measured = self._bytes_from_server(encoding)
        pixels = scenes.SIZE[0] * scenes.SIZE[1]
        # A capture that never asked for pixels is a few hundred bytes of
        # handshake, and two of those compare equal for the wrong reason.
        self.assertGreater(raw, pixels, f"raw sent {raw} bytes for {pixels} pixels; nothing was captured")
        self.assertLess(
            measured, raw,
            f"{encoding} sent {measured} bytes against raw's {raw} for scene {scene!r} "
            f"at {scenes.SIZE[0]}x{scenes.SIZE[1]}",
        )

    def test_hextile_sends_less_than_raw(self) -> None:
        self._assert_sends_less_than_raw("hextile", FLAT)

    def test_tight_sends_less_than_raw_on_flat_regions(self) -> None:
        self._assert_sends_less_than_raw("tight", FLAT)

    def test_tight_sends_less_than_raw_on_dense_detail(self) -> None:
        self._assert_sends_less_than_raw("tight", DENSE)
