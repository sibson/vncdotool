"""Capture and replay, joined: does what vnclog writes still decode the same?

test_proxy.py checks a capture by reading the archive, test_replay.py
checks replay against bytes the test itself built. A capture vnclog writes
but replay cannot serve passes both.

The two screenshots decode from the same recorded bytes, so they are
identical by construction, not by the server holding still.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from .test_proxy import _await_capture, _start_vnclog, _stop_proxy
from .vncservers import DOCKER_SERVERS, HOST, port_open, vncdo_argv

TIGERVNC = next(s for s in DOCKER_SERVERS if s.name == "tigervnc")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_TOOL = REPO_ROOT / "tests" / "tools" / "replay_capture.py"

ROUNDTRIP_PROXY_PORT = 5996
REPLAY_PORT = 5997
REPLAY_TIMEOUT = 60.0
SCREENSHOT = "screen.png"


class TestCaptureReplayRoundtrip(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.skipTest(f"tigervnc not reachable on {HOST}:{TIGERVNC.port} -- {TIGERVNC.how_to_start}")
        self.tmp = Path(tempfile.mkdtemp())
        self.live = self.tmp / "live"
        self.replayed = self.tmp / "replayed"
        self.live.mkdir()
        self.replayed.mkdir()
        self.capture = self.tmp / "roundtrip.zip"
        self.proxy = _start_vnclog(ROUNDTRIP_PROXY_PORT, f"{HOST}::{TIGERVNC.port}", self.capture)
        self.addCleanup(_stop_proxy, self.proxy)

    def test_replayed_capture_decodes_to_the_same_screenshot(self) -> None:
        # A relative filename, run from its own directory: replay drives the
        # recorded session again, and an absolute one would overwrite the
        # very screenshot it is being compared against.
        proxied = TIGERVNC._replace(port=ROUNDTRIP_PROXY_PORT)
        result = subprocess.run(
            vncdo_argv(proxied, "capture", SCREENSHOT),
            capture_output=True, text=True, timeout=REPLAY_TIMEOUT,
            stdin=subprocess.DEVNULL, cwd=self.live,
        )
        self.assertEqual(result.returncode, 0, f"vncdo via the capture proxy failed: {result.stderr}")

        _await_capture(self.capture).close()

        replay = subprocess.run(
            [
                sys.executable, str(REPLAY_TOOL), str(self.capture),
                "--listen", str(REPLAY_PORT),
                "--workdir", str(self.replayed),
                "--screenshot", SCREENSHOT,
            ],
            capture_output=True, text=True, timeout=REPLAY_TIMEOUT, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(
            replay.returncode, 0,
            f"replaying the capture failed; replay_capture said:\n{replay.stderr}",
        )

        with Image.open(self.live / SCREENSHOT) as live, Image.open(self.replayed / SCREENSHOT) as replayed:
            self.assertEqual(live.size, replayed.size, "replayed capture decoded to a different geometry")
            self.assertEqual(
                live.convert("RGB").tobytes(),
                replayed.convert("RGB").tobytes(),
                "replayed capture decoded to different pixels than the session it recorded",
            )
