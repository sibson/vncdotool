"""The `vnclog` recording proxy, driven end to end as a subprocess.

A `vnclog` process sits between `vncdo` and the vncev fleet service, and
the test asserts both sides of the proxy did their job: the events reached
the server and the recorder wrote them down.
"""

import subprocess
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from .vncservers import HOST, VNCEV, port_open, run_vncdo

PROXY_PORT = 5993
PROXY_STARTUP_DEADLINE = 10.0
PROXY_SHUTDOWN_TIMEOUT = 10.0


class TestVnclogProxy(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.skipTest(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        # --forever with a directory OUTPUT is the one recorder mode that
        # flushes its .vdo file on client disconnect rather than on clean
        # process exit, which a tearDown terminate() can't guarantee.
        self.output_dir = Path(tempfile.mkdtemp())
        self.proxy = subprocess.Popen(
            [
                "vnclog",
                "-s", f"{HOST}::{VNCEV.port}",
                "--listen", str(PROXY_PORT),
                "--forever",
                str(self.output_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        deadline = time.monotonic() + PROXY_STARTUP_DEADLINE
        while time.monotonic() < deadline and not port_open(HOST, PROXY_PORT):
            if self.proxy.poll() is not None:
                break
            time.sleep(0.2)
        if not port_open(HOST, PROXY_PORT):
            self.proxy.kill()
            self.proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)
            self.fail(f"vnclog never listened on {PROXY_PORT}; stderr:\n{self.proxy.stderr.read()}")

    def tearDown(self) -> None:
        self._stop_proxy()

    def _stop_proxy(self) -> None:
        if self.proxy.poll() is None:
            self.proxy.terminate()
            try:
                self.proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.proxy.kill()
                self.proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)

    def test_keypress_is_recorded_and_forwarded(self) -> None:
        proxied = VNCEV._replace(port=PROXY_PORT)
        result = run_vncdo(proxied, "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        # The flush lands when the recorder notices the disconnect, which
        # can lag the vncdo exit.
        deadline = time.monotonic() + PROXY_SHUTDOWN_TIMEOUT
        recorded = ""
        while time.monotonic() < deadline and "keyup z" not in recorded:
            recorded = "".join(p.read_text() for p in sorted(self.output_dir.glob("*.vdo")))
            time.sleep(0.2)
        self.assertIn("keydown z", recorded, f"vnclog recorded:\n{recorded!r}")
        self.assertIn("keyup z", recorded, f"vnclog recorded:\n{recorded!r}")
