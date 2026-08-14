"""The `vnclog` recording proxy, driven end to end as a subprocess.

A `vnclog` process sits between `vncdo` and the vncev fleet service, and
the test asserts both sides of the proxy did their job: the events reached
the server and the recorder wrote them down.

The `--capture` classes run against vncev (auth None) and against
tigervnc-auth, so the challenge/response scrub is proven against a real
server's byte stream, not only the scripted bytes in tests/unit/test_capture.py.
"""

import json
import select
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from .vncservers import DOCKER_SERVERS, HOST, VNCEV, port_open, run_vncdo

TIGERVNC_AUTH = next(s for s in DOCKER_SERVERS if s.name == "tigervnc-auth")

PROXY_PORT = 5993
CAPTURE_PROXY_PORT = 5994
CAPTURE_AUTH_PROXY_PORT = 5995
PROXY_STARTUP_DEADLINE = 10.0
PROXY_SHUTDOWN_TIMEOUT = 10.0


def _start_vnclog(listen_port: int, server: str, capture_dir: Path) -> subprocess.Popen:
    """Start `vnclog --capture`, waiting until it is actually listening.

    Readiness comes from vnclog's stderr, never a port probe: in capture
    mode the probe can race the forwarded greeting into looking like a real
    session, claim the capture, and get the actual client refused.
    """
    proxy = subprocess.Popen(
        [
            "vnclog",
            "-s", server,
            "--listen", str(listen_port),
            "--capture", str(capture_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    deadline = time.monotonic() + PROXY_STARTUP_DEADLINE
    ready = False
    while time.monotonic() < deadline and not ready:
        if proxy.poll() is not None:
            break
        rlist, _, _ = select.select([proxy.stderr], [], [], 0.2)
        if rlist and "accepting connections" in proxy.stderr.readline():
            ready = True
    if not ready:
        proxy.kill()
        proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)
        raise AssertionError(f"vnclog never listened on {listen_port}; stderr:\n{proxy.stderr.read()}")
    return proxy


def _stop_proxy(proxy: subprocess.Popen) -> None:
    if proxy.poll() is None:
        proxy.terminate()
        try:
            proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)


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


class TestVnclogCapture(TestCase):
    """`vnclog --capture DIR` end to end against vncev.

    vncev speaks auth None, so this is the no-scrub path: the four files
    land and stay byte-identical when there is nothing to redact.
    """

    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.skipTest(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture_dir = Path(tempfile.mkdtemp()) / "capture"
        self.proxy = _start_vnclog(CAPTURE_PROXY_PORT, f"{HOST}::{VNCEV.port}", self.capture_dir)

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_capture_writes_scrubbed_streams_and_meta(self) -> None:
        proxied = VNCEV._replace(port=CAPTURE_PROXY_PORT)
        result = run_vncdo(proxied, "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        expected = {"session.vdo", "s2c.bin", "c2s.bin", "meta.json"}
        deadline = time.monotonic() + PROXY_SHUTDOWN_TIMEOUT
        present: set = set()
        while time.monotonic() < deadline and not expected.issubset(present):
            present = {p.name for p in self.capture_dir.glob("*")} if self.capture_dir.is_dir() else set()
            time.sleep(0.2)
        self.assertEqual(expected, present, f"capture dir has: {sorted(present)}")

        s2c = (self.capture_dir / "s2c.bin").read_bytes()
        c2s = (self.capture_dir / "c2s.bin").read_bytes()
        self.assertTrue(s2c.startswith(b"RFB "), f"s2c.bin did not start with the server greeting: {s2c[:16]!r}")
        self.assertTrue(c2s.startswith(b"RFB "), f"c2s.bin did not start with the client's version reply: {c2s[:16]!r}")

        meta = json.loads((self.capture_dir / "meta.json").read_text())
        for key in ("server", "vncdotool_version", "capture_timestamp", "protocol_version", "security_types", "scrubbed"):
            self.assertIn(key, meta)
        self.assertEqual(meta["scrubbed"], [])  # vncev is auth None: nothing to scrub

    def test_capture_refuses_nonempty_dir(self) -> None:
        # A second vnclog pointed at the same (now non-empty) capture dir
        # must refuse rather than silently mixing captures.
        proxied = VNCEV._replace(port=CAPTURE_PROXY_PORT)
        run_vncdo(proxied, "key", "z")
        deadline = time.monotonic() + PROXY_SHUTDOWN_TIMEOUT
        while time.monotonic() < deadline and not (self.capture_dir / "meta.json").exists():
            time.sleep(0.2)
        self.assertTrue((self.capture_dir / "meta.json").exists(), "first capture never completed")

        second = subprocess.run(
            [
                "vnclog",
                "-s", f"{HOST}::{VNCEV.port}",
                "--listen", str(CAPTURE_PROXY_PORT + 1),
                "--capture", str(self.capture_dir),
            ],
            capture_output=True,
            text=True,
            timeout=PROXY_STARTUP_DEADLINE,
        )
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("empty", second.stderr.lower())


class TestVnclogCaptureVncAuth(TestCase):
    """`vnclog --capture DIR` against tigervnc-auth (VNC password auth).

    The unit tests scrub a scripted challenge/response; only a live run
    proves it against tigervnc's real handshake.
    """

    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC_AUTH.port):
            self.skipTest(
                f"tigervnc-auth not reachable on {HOST}:{TIGERVNC_AUTH.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture_dir = Path(tempfile.mkdtemp()) / "capture"
        self.proxy = _start_vnclog(CAPTURE_AUTH_PROXY_PORT, f"{HOST}::{TIGERVNC_AUTH.port}", self.capture_dir)

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_capture_scrubs_vnc_auth_challenge_and_response(self) -> None:
        proxied = TIGERVNC_AUTH._replace(port=CAPTURE_AUTH_PROXY_PORT)
        result = run_vncdo(proxied, "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        expected = {"session.vdo", "s2c.bin", "c2s.bin", "meta.json"}
        deadline = time.monotonic() + PROXY_SHUTDOWN_TIMEOUT
        present: set = set()
        while time.monotonic() < deadline and not expected.issubset(present):
            present = {p.name for p in self.capture_dir.glob("*")} if self.capture_dir.is_dir() else set()
            time.sleep(0.2)
        self.assertEqual(expected, present, f"capture dir has: {sorted(present)}")

        s2c = (self.capture_dir / "s2c.bin").read_bytes()
        c2s = (self.capture_dir / "c2s.bin").read_bytes()
        self.assertTrue(s2c.startswith(b"RFB "), f"s2c.bin did not start with the server greeting: {s2c[:16]!r}")
        self.assertTrue(c2s.startswith(b"RFB "), f"c2s.bin did not start with the client's version reply: {c2s[:16]!r}")

        # More than the handshake: post-auth client traffic proves nothing
        # truncated the recording at the auth exchange.
        HANDSHAKE_ONLY = 12 + 1 + 16
        self.assertGreater(
            len(c2s), HANDSHAKE_ONLY, f"c2s.bin looks truncated at the handshake: {len(c2s)} bytes: {c2s!r}"
        )

        # the real password must not appear anywhere in the clear
        self.assertNotIn(TIGERVNC_AUTH.password.encode(), s2c)
        self.assertNotIn(TIGERVNC_AUTH.password.encode(), c2s)

        meta = json.loads((self.capture_dir / "meta.json").read_text())
        self.assertEqual(meta["scrubbed"], ["vnc-auth-challenge", "vnc-auth-response"])
        self.assertIsNone(meta["unscrubbed_auth"])

        session_vdo = (self.capture_dir / "session.vdo").read_text()
        self.assertIn("keydown z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
        self.assertIn("keyup z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
