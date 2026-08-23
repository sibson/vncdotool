"""The only place replay meets a real client. No recorded capture is replayed."""

from __future__ import annotations

import pathlib
import socket
import subprocess
import tempfile
import zipfile
from struct import pack
from unittest import TestCase

from PIL import Image

from vncdotool.const import AuthTypes, Encoding, MsgS2C
from vncdotool.rfb import PixelFormat

from .utils import VNCDO, VNCDO_REPLAY, start_replay_server

PIXEL_FORMAT = PixelFormat()
WIDTH, HEIGHT = 2, 2
PIXELS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
GREETING = b"RFB 003.003\n"
CLIENT_TIMEOUT = 20
EXIT_TIMEOUT = 10


def _pixel(r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b, 0))


def _build_s2c() -> bytes:
    """A none-auth handshake, as a stripped capture would record it regardless
    of what the server actually demanded."""
    auth_none = pack("!I", AuthTypes.NONE)
    server_init = pack("!HH16sI", WIDTH, HEIGHT, PIXEL_FORMAT.to_bytes(), 0)
    body = b"".join(_pixel(*p) for p in PIXELS)
    rect = pack("!HHHHi", 0, 0, WIDTH, HEIGHT, int(Encoding.RAW)) + body
    fbu = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1) + rect
    return GREETING + auth_none + server_init + fbu


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestReplayEndToEnd(TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.archive = self.tmp / "capture.zip"
        with zipfile.ZipFile(self.archive, "w") as zf:
            zf.writestr("s2c.bin", _build_s2c())
            zf.writestr("session.vdo", b"key a\n")
        self.port = _free_port()

    def _serve(self) -> subprocess.Popen:
        # --forever: the readiness probe is just another client, not the
        # one connection this server had to give.
        return start_replay_server(self, self.archive, self.port)

    def test_recorded_session_replays_and_decodes_expected_pixels(self) -> None:
        server = self._serve()
        out_png = self.tmp / "out.png"
        try:
            result = subprocess.run(
                [
                    VNCDO_REPLAY, "-s", f"127.0.0.1::{self.port}", str(self.archive),
                    "capture", str(out_png),
                ],
                capture_output=True, text=True, timeout=CLIENT_TIMEOUT, stdin=subprocess.DEVNULL,
            )
        finally:
            server.terminate()
            server.communicate(timeout=EXIT_TIMEOUT)

        self.assertEqual(result.returncode, 0, f"vncdo-replay client failed: {result.stderr}")

        image = Image.open(out_png).convert("RGB")
        self.assertEqual(image.size, (WIDTH, HEIGHT))
        for i, want in enumerate(PIXELS):
            x, y = i % WIDTH, i // WIDTH
            self.assertEqual(image.getpixel((x, y)), want, f"pixel mismatch at ({x}, {y})")

    def test_a_plain_vncdo_can_take_the_client_side_instead(self) -> None:
        """Anything can be the client: a GUI viewer, or vncdo by hand."""
        server = self._serve()
        out_png = self.tmp / "byhand.png"
        try:
            result = subprocess.run(
                [VNCDO, "-s", f"127.0.0.1::{self.port}", "capture", str(out_png)],
                capture_output=True, text=True, timeout=CLIENT_TIMEOUT, stdin=subprocess.DEVNULL,
            )
        finally:
            server.terminate()
            server.communicate(timeout=EXIT_TIMEOUT)

        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")
        with Image.open(out_png) as image:
            self.assertEqual(image.size, (WIDTH, HEIGHT))
