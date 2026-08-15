"""End-to-end test for tests/tools/replay_capture.py.

No docker, no fleet: a hand-built capture is served by the replay tool in
its own process, which forks the real `vncdo` CLI at it, and the resulting
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
import zipfile
from struct import pack
from unittest import TestCase

from PIL import Image

from vncdotool.const import AuthTypes, Encoding, MsgS2C
from vncdotool.rfb import PixelFormat

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tests" / "tools" / "replay_capture.py"

PIXEL_FORMAT = PixelFormat()
WIDTH, HEIGHT = 2, 2
PIXELS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
GREETING = b"RFB 003.003\n"
REPLAY_TIMEOUT = 30


def _pixel(r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b, 0))


def _build_s2c() -> bytes:
    """greeting + pre-3.8 AuthTypes.NONE handshake + ServerInit + one raw FBU."""
    auth_none = pack("!I", AuthTypes.NONE)
    server_init = pack("!HH16sI", WIDTH, HEIGHT, PIXEL_FORMAT.to_bytes(), 0)
    body = b"".join(_pixel(*p) for p in PIXELS)
    rect = pack("!HHHHi", 0, 0, WIDTH, HEIGHT, int(Encoding.RAW)) + body
    fbu = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1) + rect
    return GREETING + auth_none + server_init + fbu


def _build_c2s() -> bytes:
    """The original client's side, which is what says where the handshake ends."""
    return GREETING + b"\x01"  # ClientInit, shared=1


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestReplayCaptureEndToEnd(TestCase):
    def test_vncdo_capture_decodes_expected_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            archive = tmpdir / "capture.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("s2c.bin", _build_s2c())
                zf.writestr("c2s.bin", _build_c2s())

            out_png = tmpdir / "out.png"
            argv = [
                sys.executable, str(TOOL_PATH), str(archive),
                "--listen", str(_free_port()),
                "--workdir", str(tmpdir),
                "--screenshot", out_png.name,
            ]
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=REPLAY_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )

            self.assertEqual(
                result.returncode, 0,
                f"replay_capture exited {result.returncode}; it reported:\n{result.stderr}",
            )
            self.assertTrue(out_png.exists(), f"no screenshot written; tool said:\n{result.stderr}")

            image = Image.open(out_png).convert("RGB")
            self.assertEqual(image.size, (WIDTH, HEIGHT))
            for i, want in enumerate(PIXELS):
                x, y = i % WIDTH, i // WIDTH
                self.assertEqual(image.getpixel((x, y)), want, f"pixel mismatch at ({x}, {y})")
