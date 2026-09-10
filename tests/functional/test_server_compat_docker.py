"""The critical user journey: connect, send input, capture a screen.

Run first and cheaply, so `vncdo` breaking outright fails here rather than
part-way through the suites that take minutes.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

from vncdotool.command import ExitStatus

from .utils import KASMVNC, SUPPORTED_SERVERS, FleetTestCase, register_server_tests, run_vncdo

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests(SUPPORTED_SERVERS, globals(), base=FleetTestCase)


class TestKasmVNCInput(FleetTestCase):
    server = KASMVNC
    # Long enough that a served update arrives, short enough that the wedge
    # surfaces well before KasmVNC's own 20-second idle timeout drops the
    # socket.
    deadline = "5"

    def capture_after(self, *args: str) -> Tuple[subprocess.CompletedProcess, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        png = Path(tmp.name) / "after-input.png"
        result = run_vncdo(
            self.server, "--timeout", self.deadline,
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
            "now reads the RFB 6143 message: its accepts_pointer_events=False "
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
