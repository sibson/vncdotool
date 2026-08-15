"""End-to-end test for tests/tools/replay_server.py.

No docker, no fleet: a hand-built capture is served by the replay tool in
its own process, the real `vncdo` CLI is pointed at it, and the resulting
PNG is checked pixel-exactly. Two processes rather than threads, because
each runs its own Twisted reactor.

This is the only place the tool meets a real client instead of a mocked
transport; no recorded capture is ever replayed here.
"""

from __future__ import annotations

import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from struct import pack
from unittest import TestCase

from PIL import Image

from vncdotool.const import AuthTypes, Encoding, MsgS2C
from vncdotool.rfb import PixelFormat

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tests" / "tools" / "replay_server.py"

PIXEL_FORMAT = PixelFormat()
WIDTH, HEIGHT = 2, 2
PIXELS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
LISTEN_TIMEOUT = 10
VNCDO_TIMEOUT = 15
EXIT_TIMEOUT = 10


def _pixel(r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b, 0))


def _build_capture() -> bytes:
    """greeting + pre-3.8 AuthTypes.NONE handshake + ServerInit + one raw FBU."""
    greeting = b"RFB 003.003\n"
    auth_none = pack("!I", AuthTypes.NONE)
    server_init = pack("!HH16sI", WIDTH, HEIGHT, PIXEL_FORMAT.to_bytes(), 0)
    body = b"".join(_pixel(*p) for p in PIXELS)
    rect = pack("!HHHHi", 0, 0, WIDTH, HEIGHT, int(Encoding.RAW)) + body
    fbu = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1) + rect
    return greeting + auth_none + server_init + fbu


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


class TestReplayServerEndToEnd(TestCase):
    def test_vncdo_capture_decodes_expected_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            archive = tmpdir / "capture.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("s2c.bin", _build_capture())

            port = _free_port()
            # --forever, so the readiness probe below is just another client
            # rather than the one connection this server had to give.
            server = subprocess.Popen(
                [
                    sys.executable, str(TOOL_PATH), "--capture", str(archive),
                    "--listen", str(port), "--forever",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(server.kill)
            self.addCleanup(server.stdout.close)
            self.addCleanup(server.stderr.close)

            if not _wait_until_listening(port, time.monotonic() + LISTEN_TIMEOUT):
                server.kill()
                self.fail(f"replay_server never listened on {port}: {server.communicate()[1]}")

            out_png = tmpdir / "out.png"
            argv = ["vncdo", "-s", f"127.0.0.1::{port}", "capture", str(out_png)]
            try:
                result = subprocess.run(
                    argv, capture_output=True, text=True, timeout=VNCDO_TIMEOUT,
                    stdin=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                raise AssertionError(
                    f"`{argv[0]}` not found on PATH -- install vncdotool (`pip install -e .`) "
                    "so its console script is available"
                ) from exc
            finally:
                server.terminate()
                server.communicate(timeout=EXIT_TIMEOUT)

            self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

            image = Image.open(out_png).convert("RGB")
            self.assertEqual(image.size, (WIDTH, HEIGHT))
            for i, want in enumerate(PIXELS):
                x, y = i % WIDTH, i // WIDTH
                self.assertEqual(image.getpixel((x, y)), want, f"pixel mismatch at ({x}, {y})")
