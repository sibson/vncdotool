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
import time
from pathlib import Path
from unittest import TestCase

from PIL import Image

from .test_proxy import _await_capture, _start_vnclog, _stop_proxy
from .vncservers import DOCKER_SERVERS, HOST, port_open, run_vncdo

TIGERVNC = next(s for s in DOCKER_SERVERS if s.name == "tigervnc")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_TOOL = REPO_ROOT / "tests" / "tools" / "replay_server.py"

ROUNDTRIP_PROXY_PORT = 5996
REPLAY_PORT = 5997
REPLAY_STARTUP_DEADLINE = 10.0
REPLAY_SHUTDOWN_TIMEOUT = 10.0


class TestCaptureReplayRoundtrip(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.skipTest(f"tigervnc not reachable on {HOST}:{TIGERVNC.port} -- {TIGERVNC.how_to_start}")
        self.tmp = Path(tempfile.mkdtemp())
        self.capture = self.tmp / "roundtrip.zip"
        self.proxy = _start_vnclog(ROUNDTRIP_PROXY_PORT, f"{HOST}::{TIGERVNC.port}", self.capture)
        self.addCleanup(_stop_proxy, self.proxy)

    def test_replayed_capture_decodes_to_the_same_screenshot(self) -> None:
        live_png = self.tmp / "live.png"
        proxied = TIGERVNC._replace(port=ROUNDTRIP_PROXY_PORT)
        result = run_vncdo(proxied, "capture", str(live_png))
        self.assertEqual(result.returncode, 0, f"vncdo via the capture proxy failed: {result.stderr}")

        _await_capture(self.capture).close()

        replayed_png = self.tmp / "replayed.png"
        server = self._start_replay()
        try:
            replayed = run_vncdo(
                TIGERVNC._replace(port=REPLAY_PORT, password=None), "capture", str(replayed_png)
            )
        finally:
            server.terminate()
            stdout, stderr = server.communicate(timeout=REPLAY_SHUTDOWN_TIMEOUT)

        self.assertEqual(
            replayed.returncode, 0,
            f"vncdo against the replayed capture failed: {replayed.stderr}\n"
            f"replay_server said:\n{stderr}",
        )

        with Image.open(live_png) as live, Image.open(replayed_png) as replay:
            self.assertEqual(live.size, replay.size, "replayed capture decoded to a different geometry")
            self.assertEqual(
                live.convert("RGB").tobytes(),
                replay.convert("RGB").tobytes(),
                "replayed capture decoded to different pixels than the session it recorded",
            )

    def _start_replay(self) -> subprocess.Popen:
        """Serve the capture, waiting until the port answers.

        --forever, so this readiness probe does not consume the one
        connection the replay had to give.
        """
        server = subprocess.Popen(
            [
                sys.executable, str(REPLAY_TOOL),
                "--capture", str(self.capture),
                "--listen", str(REPLAY_PORT),
                "--forever",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        self.addCleanup(server.kill)
        self.addCleanup(server.stdout.close)
        self.addCleanup(server.stderr.close)
        deadline = time.monotonic() + REPLAY_STARTUP_DEADLINE
        while time.monotonic() < deadline and not port_open(HOST, REPLAY_PORT):
            if server.poll() is not None:
                self.fail(f"replay_server exited before listening; stderr:\n{server.stderr.read()}")
            time.sleep(0.2)
        if not port_open(HOST, REPLAY_PORT):
            server.kill()
            self.fail(f"replay_server never listened on {REPLAY_PORT}")
        return server
