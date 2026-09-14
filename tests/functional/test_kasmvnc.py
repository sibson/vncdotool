"""What KasmVNC does with a PointerEvent, and what --dialect kasmvnc does about it.

Kept out of test_server_compat_docker.py, which CI runs twice: once as the
smoke step that fails early, then again with the rest of the suite. These
cases spend their time waiting out timeouts, which is the opposite of what
the smoke step is for.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

from vncdotool.command import ExitStatus

from .utils import KASMVNC, FleetTestCase, run_vncdo


class TestKasmVNCInput(FleetTestCase):
    """Locks the KasmVNC behaviour that keeps it out of SUPPORTED_SERVERS.

    A failure here means the server changed: re-evaluate whether it moves
    back to README.md's Supported class.
    """

    server = KASMVNC
    # Long enough that a served update arrives, short enough that the wedge
    # surfaces well before KasmVNC's own 20-second idle timeout drops the
    # socket.
    timeout = "5"

    def capture_after(self, *args: str) -> Tuple[subprocess.CompletedProcess, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        png = Path(tmp.name) / "after-input.png"
        result = run_vncdo(
            self.server, "--timeout", self.timeout,
            *args, "pause", "0.3", "capture", str(png),
        )
        return result, png

    def test_a_key_event_leaves_the_session_answering(self) -> None:
        result, png = self.capture_after("key", "x")
        self.assertEqual(
            result.returncode, 0,
            f"KasmVNC: vncdo exited {result.returncode} after a KeyEvent, "
            f"stderr:\n{result.stderr}",
        )
        self.assertTrue(
            png.exists(),
            "KasmVNC served no framebuffer update after a KeyEvent; only its "
            "PointerEvent is known to differ from RFB 6143",
        )

    def test_a_pointer_event_stops_the_session_answering(self) -> None:
        result, png = self.capture_after("move", "10", "10")
        self.assertFalse(
            png.exists(),
            "KasmVNC served a framebuffer update after a PointerEvent, so it "
            "now reads the RFB 6143 message: its skip_pointer_tests=True "
            "and its README.md Broken entry are both wrong",
        )
        self.assertEqual(
            result.returncode, ExitStatus.TIMEOUT,
            f"KasmVNC: capture after a PointerEvent produced no PNG, but vncdo "
            f"exited {result.returncode} rather than timing out, stderr:\n"
            f"{result.stderr}",
        )

    def test_the_kasmvnc_dialect_keeps_the_session_answering(self) -> None:
        result, png = self.capture_after("--dialect", "kasmvnc", "move", "10", "10")
        self.assertEqual(
            result.returncode, 0,
            f"KasmVNC: --dialect kasmvnc exited {result.returncode}, stderr:\n"
            f"{result.stderr}",
        )
        self.assertTrue(
            png.exists(),
            "KasmVNC served no framebuffer update after an eleven-byte "
            "PointerEvent, so --dialect kasmvnc no longer matches its reader",
        )
