"""End-to-end socket test for tests/tools/replay_server.py.

No docker, no fleet: a hand-built capture is served on a loopback port by
the replay tool itself, the real `vncdo` CLI is pointed at it, and the
resulting PNG is checked pixel-exactly. This is the only place the handshake logic
runs against a real client rather than a scripted fake one.
"""

from __future__ import annotations

import importlib.util
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
from struct import pack
from unittest import TestCase

from PIL import Image

from vncdotool.const import AuthTypes, Encoding, MsgS2C
from vncdotool.rfb import PixelFormat

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TOOL_PATH = REPO_ROOT / "tests" / "tools" / "replay_server.py"
_spec = importlib.util.spec_from_file_location("replay_server_tool", _TOOL_PATH)
replay_server = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# Registered before exec'ing, for the dataclass() reason in
# tests/unit/test_replay_server.py.
sys.modules[_spec.name] = replay_server
_spec.loader.exec_module(replay_server)

PIXEL_FORMAT = PixelFormat()
WIDTH, HEIGHT = 2, 2
PIXELS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
ACCEPT_TIMEOUT = 10
JOIN_TIMEOUT = 10


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


class TestReplayServerEndToEnd(TestCase):
    def test_vncdo_capture_decodes_expected_pixels(self) -> None:
        s2c_data = _build_capture()

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        port = server_sock.getsockname()[1]
        server_sock.listen(1)

        errors: list[Exception] = []

        def _serve() -> None:
            server_sock.settimeout(ACCEPT_TIMEOUT)
            try:
                conn, _addr = server_sock.accept()
            except OSError as exc:
                errors.append(exc)
                return
            try:
                replay_server.handle_capture_connection(conn, s2c_data, wait_for_client=True, verbose=False)
            except Exception as exc:  # noqa: BLE001 -- surfaced via `errors` to the test thread
                errors.append(exc)
            finally:
                conn.close()

        server_thread = threading.Thread(target=_serve, daemon=True)
        server_thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_png = pathlib.Path(tmp) / "out.png"
                argv = ["vncdo", "-s", f"127.0.0.1::{port}", "capture", str(out_png)]
                try:
                    # stdin closed so an unexpected getpass() prompt fails
                    # instead of blocking.
                    result = subprocess.run(
                        argv, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL
                    )
                except FileNotFoundError as exc:
                    raise AssertionError(
                        f"`{argv[0]}` not found on PATH -- install vncdotool (`pip install -e .`) "
                        "so its console script is available"
                    ) from exc
                self.assertEqual(result.returncode, 0, f"vncdo failed: {result.stderr}")

                image = Image.open(out_png).convert("RGB")
                self.assertEqual(image.size, (WIDTH, HEIGHT))
                for i, want in enumerate(PIXELS):
                    x, y = i % WIDTH, i // WIDTH
                    self.assertEqual(image.getpixel((x, y)), want, f"pixel mismatch at ({x}, {y})")
        finally:
            server_thread.join(timeout=JOIN_TIMEOUT)
            server_sock.close()

        self.assertFalse(server_thread.is_alive(), "replay server thread did not finish -- looks wedged")
        self.assertEqual(errors, [], f"replay server thread raised: {errors}")
