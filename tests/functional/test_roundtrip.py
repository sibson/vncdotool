"""Capture and replay, joined: does what vnclog writes still decode the same?

tigervnc demands a password; the archive of it does not."""

import subprocess
import time
from pathlib import Path
from tempfile import mkdtemp
from unittest import TestCase

from PIL import Image

from .test_proxy import _await_capture, _start_vnclog, _stop_proxy
from .vncservers import DOCKER_SERVERS, HOST, port_open, vncdo_argv

TIGERVNC = next(s for s in DOCKER_SERVERS if s.name == "tigervnc")

ROUNDTRIP_PROXY_PORT = 5996
REPLAY_PORT = 5997
REPLAY_STARTUP_DEADLINE = 10.0
TIMEOUT = 60.0
SCREENSHOT = "screen.png"


class TestCaptureReplayRoundtrip(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.skipTest(f"tigervnc not reachable on {HOST}:{TIGERVNC.port} -- {TIGERVNC.how_to_start}")
        self.tmp = Path(mkdtemp())
        self.live = self.tmp / "live"
        self.replayed = self.tmp / "replayed"
        self.live.mkdir()
        self.replayed.mkdir()
        self.capture = self.tmp / "roundtrip.zip"
        self.proxy = _start_vnclog(ROUNDTRIP_PROXY_PORT, f"{HOST}::{TIGERVNC.port}", self.capture)
        self.addCleanup(_stop_proxy, self.proxy)

    def test_replayed_capture_decodes_to_the_same_screenshot(self) -> None:
        # Relative, from its own directory: an absolute path would have the
        # replay overwrite the file it is compared against.
        proxied = TIGERVNC._replace(port=ROUNDTRIP_PROXY_PORT)
        result = subprocess.run(
            vncdo_argv(proxied, "capture", SCREENSHOT),
            capture_output=True, text=True, timeout=TIMEOUT,
            stdin=subprocess.DEVNULL, cwd=self.live,
        )
        self.assertEqual(result.returncode, 0, f"vncdo via the capture proxy failed: {result.stderr}")

        _await_capture(self.capture).close()

        server = self._start_replay()
        try:
            # No -p: tigervnc demanded a password, the capture of it does not.
            replayed = subprocess.run(
                [
                    "vncdo-replay", "-s", f"{HOST}::{REPLAY_PORT}", str(self.capture),
                    "capture", SCREENSHOT,
                ],
                capture_output=True, text=True, timeout=TIMEOUT,
                stdin=subprocess.DEVNULL, cwd=self.replayed,
            )
        finally:
            server.terminate()
            stdout, stderr = server.communicate(timeout=TIMEOUT)

        self.assertEqual(
            replayed.returncode, 0,
            f"vncdo-replay against the replayed capture failed: {replayed.stderr}\n"
            f"the replay server said:\n{stderr}",
        )

        with Image.open(self.live / SCREENSHOT) as live, Image.open(self.replayed / SCREENSHOT) as replay:
            self.assertEqual(live.size, replay.size, "replayed capture decoded to a different geometry")
            self.assertEqual(
                live.convert("RGB").tobytes(),
                replay.convert("RGB").tobytes(),
                "replayed capture decoded to different pixels than the session it recorded",
            )

    def _start_replay(self) -> subprocess.Popen:
        """Serve the capture, waiting until the port answers."""
        server = subprocess.Popen(
            [
                "vncdo-replay", "--server", str(self.capture),
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
                self.fail(f"vncdo-replay --server exited before listening; stderr:\n{server.stderr.read()}")
            time.sleep(0.2)
        if not port_open(HOST, REPLAY_PORT):
            server.kill()
            self.fail(f"vncdo-replay --server never listened on {REPLAY_PORT}")
        return server
