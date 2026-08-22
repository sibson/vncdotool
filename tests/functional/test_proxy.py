"""The `vnclog` recording proxy, driven end to end as a subprocess."""

import json
import select
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import TestCase

from vncdotool.const import AuthTypes

from .utils import HOST, TIGERVNC_AUTH, VNCEV, VNCLOG, port_open, run_vncdo

PROXY_PORT = 5993
CAPTURE_PROXY_PORT = 5994
CAPTURE_AUTH_PROXY_PORT = 5995
AUTH_PROXY_PORT = 5998
PROXY_STARTUP_DEADLINE = 10.0
PROXY_SHUTDOWN_TIMEOUT = 10.0


def _await_capture(archive: Path) -> zipfile.ZipFile:
    """Wait for the capture archive to be written, then open it.

    The archive is renamed into place only once complete, so its existence
    is enough -- no polling for individual members.
    """
    deadline = time.monotonic() + PROXY_SHUTDOWN_TIMEOUT
    while time.monotonic() < deadline and not archive.exists():
        time.sleep(0.2)
    if not archive.exists():
        raise AssertionError(f"capture archive {archive} was never written")
    return zipfile.ZipFile(archive)


def _start_vnclog(listen_port: int, server: str, *recorder_args: str) -> subprocess.Popen:
    """Readiness comes from vnclog's stderr, never a port probe: the probe can
    race the forwarded greeting into looking like a real session.
    """
    proxy = subprocess.Popen(
        [VNCLOG, "-s", server, "--listen", str(listen_port), *recorder_args],
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


def _await_recorded(output_dir: Path, marker: str, deadline_seconds: float = PROXY_SHUTDOWN_TIMEOUT) -> str:
    """The flush lands when the recorder notices the client disconnect, which can lag vncdo's own exit."""
    deadline = time.monotonic() + deadline_seconds
    recorded = ""
    while time.monotonic() < deadline and marker not in recorded:
        recorded = "".join(p.read_text() for p in sorted(output_dir.glob("*.vdo")))
        time.sleep(0.2)
    return recorded


def _stop_proxy(proxy: subprocess.Popen) -> None:
    if proxy.poll() is None:
        proxy.terminate()
        try:
            proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait(timeout=PROXY_SHUTDOWN_TIMEOUT)


class TestVNCLOGProxy(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.fail(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.output_dir = Path(tempfile.mkdtemp())
        self.proxy = _start_vnclog(PROXY_PORT, f"{HOST}::{VNCEV.port}", "--file-per-client", str(self.output_dir))

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_keypress_is_recorded_and_forwarded(self) -> None:
        proxied = VNCEV._replace(port=PROXY_PORT)
        result = run_vncdo(proxied, "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        recorded = _await_recorded(self.output_dir, "keyup z")
        self.assertIn("keydown z", recorded, f"vnclog recorded:\n{recorded!r}")
        self.assertIn("keyup z", recorded, f"vnclog recorded:\n{recorded!r}")


class TestVNCLOGProxyAuth(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC_AUTH.port):
            self.fail(
                f"tigervnc-auth not reachable on {HOST}:{TIGERVNC_AUTH.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.output_dir = Path(tempfile.mkdtemp())
        self.proxy = _start_vnclog(
            AUTH_PROXY_PORT, f"{HOST}::{TIGERVNC_AUTH.port}", "--file-per-client", str(self.output_dir)
        )

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_move_and_keypress_are_recorded_and_forwarded(self) -> None:
        proxied = TIGERVNC_AUTH._replace(port=AUTH_PROXY_PORT)
        result = run_vncdo(proxied, "move", "10", "10", "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        recorded = _await_recorded(self.output_dir, "keyup z")
        self.assertIn("move 10 10", recorded, f"vnclog recorded:\n{recorded!r}")
        self.assertIn("keydown z", recorded, f"vnclog recorded:\n{recorded!r}")
        self.assertIn("keyup z", recorded, f"vnclog recorded:\n{recorded!r}")


class TestVNCLOGCapture(TestCase):
    """`vnclog --capture-raw FILE.zip` against vncev, which uses auth None."""

    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.fail(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture = Path(tempfile.mkdtemp()) / "capture.zip"
        self.proxy = _start_vnclog(CAPTURE_PROXY_PORT, f"{HOST}::{VNCEV.port}", "--capture-raw", str(self.capture))

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_capture_writes_scrubbed_streams_and_meta(self) -> None:
        proxied = VNCEV._replace(port=CAPTURE_PROXY_PORT)
        # `capture` rather than a bare key press: a screenshot forces a
        # FramebufferUpdate, which is what puts rectangles on the wire for
        # meta.json's encodings_seen to count.
        screenshot = Path(tempfile.mkdtemp()) / "screen.png"
        result = run_vncdo(proxied, "key", "z", "capture", str(screenshot))
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        with _await_capture(self.capture) as archive:
            self.assertEqual(
                sorted(archive.namelist()), ["c2s.bin", "meta.json", "s2c.bin", "session.vdo"]
            )
            s2c = archive.read("s2c.bin")
            c2s = archive.read("c2s.bin")
            meta = json.loads(archive.read("meta.json"))

        self.assertTrue(s2c.startswith(b"RFB "), f"s2c.bin did not start with the server greeting: {s2c[:16]!r}")
        self.assertTrue(c2s.startswith(b"RFB "), f"c2s.bin did not start with the client's version reply: {c2s[:16]!r}")

        for key in ("server", "vncdotool_version", "capture_timestamp", "protocol_version", "security_types"):
            self.assertIn(key, meta)

        # Recorded off the decoded stream, so this is what the server chose,
        # not what the client requested.
        self.assertTrue(meta["encodings_seen"], "no rectangles were tallied")
        for seen in meta["encodings_seen"]:
            self.assertGreater(seen["rectangles"], 0)

    def test_capture_refuses_existing_target(self) -> None:
        # A second vnclog pointed at a capture that already exists must
        # refuse rather than overwrite it.
        proxied = VNCEV._replace(port=CAPTURE_PROXY_PORT)
        run_vncdo(proxied, "key", "z")
        _await_capture(self.capture).close()

        second = subprocess.run(
            [
                VNCLOG,
                "-s", f"{HOST}::{VNCEV.port}",
                "--listen", str(CAPTURE_PROXY_PORT + 1),
                "--capture-raw", str(self.capture),
            ],
            capture_output=True,
            text=True,
            timeout=PROXY_STARTUP_DEADLINE,
        )
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already exists", second.stderr.lower())


class TestVNCLOGCaptureVNCAuth(TestCase):
    """`vnclog --capture-raw FILE.zip` against tigervnc-auth.

    Only a live run proves the strip against a real handshake."""

    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC_AUTH.port):
            self.fail(
                f"tigervnc-auth not reachable on {HOST}:{TIGERVNC_AUTH.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture = Path(tempfile.mkdtemp()) / "capture.zip"
        self.proxy = _start_vnclog(
            CAPTURE_AUTH_PROXY_PORT, f"{HOST}::{TIGERVNC_AUTH.port}", "--capture-raw", str(self.capture)
        )

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_capture_strips_the_vnc_auth_handshake(self) -> None:
        proxied = TIGERVNC_AUTH._replace(port=CAPTURE_AUTH_PROXY_PORT)
        result = run_vncdo(proxied, "key", "z")
        self.assertEqual(result.returncode, 0, f"vncdo via proxy failed: {result.stderr}")

        with _await_capture(self.capture) as archive:
            self.assertEqual(
                sorted(archive.namelist()), ["c2s.bin", "meta.json", "s2c.bin", "session.vdo"]
            )
            s2c = archive.read("s2c.bin")
            c2s = archive.read("c2s.bin")
            meta = json.loads(archive.read("meta.json"))
            session_vdo = archive.read("session.vdo").decode()

        self.assertTrue(s2c.startswith(b"RFB "), f"s2c.bin did not start with the server greeting: {s2c[:16]!r}")
        self.assertTrue(c2s.startswith(b"RFB "), f"c2s.bin did not start with the client's version reply: {c2s[:16]!r}")

        # Greeting (12) + none-auth choice (1) + ClientInit (1): the whole
        # handshake with zero post-auth traffic.
        HANDSHAKE_ONLY = 12 + 1 + 1
        self.assertGreater(
            len(c2s), HANDSHAKE_ONLY, f"c2s.bin looks truncated at the handshake: {len(c2s)} bytes: {c2s!r}"
        )

        # Negotiated VNC auth; recorded as none-auth, with no challenge or response.
        self.assertEqual(meta["security_type"], int(AuthTypes.VNC_AUTHENTICATION))
        self.assertEqual(meta["auth"], "stripped")
        self.assertEqual(s2c[12:14], bytes([1, AuthTypes.NONE]), f"handshake was not stripped: {s2c[:32]!r}")
        self.assertEqual(s2c[14:18], bytes(4), f"SecurityResult missing after the strip: {s2c[:32]!r}")
        self.assertEqual(c2s[12:14], bytes([AuthTypes.NONE, 1]), f"handshake was not stripped: {c2s[:32]!r}")

        self.assertIn("keydown z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
        self.assertIn("keyup z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
