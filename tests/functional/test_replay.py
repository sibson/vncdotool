"""End-to-end test for the `vncdo-replay` CLI.

No docker, no fleet: a hand-built capture is served by `vncdo-replay
--server` in its own process, `vncdo-replay` drives the client side from
another, and the resulting PNG is checked pixel-exactly. Two processes
rather than threads, because each runs its own Twisted reactor -- which is
also why the tool is two commands rather than one.

This is the only place replay meets a real client instead of a mocked
transport; no recorded capture is ever replayed here.
"""

from __future__ import annotations

import pathlib
import socket
import subprocess
import tempfile
import time
import zipfile
from struct import pack
from unittest import TestCase

from PIL import Image

from vncdotool.const import AuthTypes, Encoding, MsgS2C
from vncdotool.rfb import PixelFormat

PIXEL_FORMAT = PixelFormat()
WIDTH, HEIGHT = 2, 2
PIXELS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
GREETING = b"RFB 003.003\n"
LISTEN_TIMEOUT = 10
CLIENT_TIMEOUT = 20
EXIT_TIMEOUT = 10


def _pixel(r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b, 0))


def _build_s2c() -> bytes:
    """greeting + pre-3.8 AuthTypes.NONE handshake + ServerInit + one raw FBU.

    The shape a stripped capture has: `vnclog --capture-raw` writes a
    none-auth handshake whatever the server demanded.
    """
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


def _wait_until_listening(port: int, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class TestReplayEndToEnd(TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.archive = self.tmp / "capture.zip"
        with zipfile.ZipFile(self.archive, "w") as zf:
            zf.writestr("s2c.bin", _build_s2c())
            zf.writestr("session.vdo", b"key a\n")
        self.port = _free_port()

    def _serve(self) -> subprocess.Popen:
        # --forever, so the readiness probe below is just another client
        # rather than the one connection this server had to give.
        argv = ["vncdo-replay", "--server", str(self.archive), "--listen", str(self.port), "--forever"]
        try:
            server = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as exc:
            raise AssertionError(
                "`vncdo-replay` not found on PATH -- install vncdotool (`pip install -e .`) "
                "so its console script is available"
            ) from exc
        self.addCleanup(server.kill)
        self.addCleanup(server.stdout.close)
        self.addCleanup(server.stderr.close)
        if not _wait_until_listening(self.port, time.monotonic() + LISTEN_TIMEOUT):
            server.kill()
            self.fail(f"vncdo-replay --server never listened on {self.port}: {server.communicate()[1]}")
        return server

    def test_recorded_session_replays_and_decodes_expected_pixels(self) -> None:
        server = self._serve()
        out_png = self.tmp / "out.png"
        try:
            result = subprocess.run(
                [
                    "vncdo-replay", "-s", f"127.0.0.1::{self.port}", str(self.archive),
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
        """The two halves are separate processes so that anything can be the
        client -- a GUI viewer, or vncdo driven by hand."""
        server = self._serve()
        out_png = self.tmp / "byhand.png"
        try:
            result = subprocess.run(
                ["vncdo", "-s", f"127.0.0.1::{self.port}", "capture", str(out_png)],
                capture_output=True, text=True, timeout=CLIENT_TIMEOUT, stdin=subprocess.DEVNULL,
            )
        finally:
            server.terminate()
            server.communicate(timeout=EXIT_TIMEOUT)

        self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")
        with Image.open(out_png) as image:
            self.assertEqual(image.size, (WIDTH, HEIGHT))
