"""The `vnclog` recording proxy, driven end to end as a subprocess."""

import json
import select
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import TestCase

from .vncservers import DOCKER_SERVERS, HOST, VNCEV, port_open, run_vncdo

TIGERVNC_AUTH = next(s for s in DOCKER_SERVERS if s.name == "tigervnc-auth")

PROXY_PORT = 5993
CAPTURE_PROXY_PORT = 5994
CAPTURE_AUTH_PROXY_PORT = 5995
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


def _start_vnclog(listen_port: int, server: str, capture_path: Path) -> subprocess.Popen:
    """Start `vnclog --capture-raw`, waiting until it is actually listening.

    Readiness comes from vnclog's stderr, never a port probe: the probe can
    race the forwarded greeting into looking like a real session.
    """
    proxy = subprocess.Popen(
        [
            "vnclog",
            "-s", server,
            "--listen", str(listen_port),
            "--capture-raw", str(capture_path),
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


class TestVNCLOGProxy(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.skipTest(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        # --file-per-client with a directory OUTPUT is the one recorder mode that
        # flushes its .vdo file on client disconnect rather than on clean
        # process exit, which a tearDown terminate() can't guarantee.
        self.output_dir = Path(tempfile.mkdtemp())
        self.proxy = subprocess.Popen(
            [
                "vnclog",
                "-s", f"{HOST}::{VNCEV.port}",
                "--listen", str(PROXY_PORT),
                "--file-per-client",
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


class TestVNCLOGCapture(TestCase):
    """`vnclog --capture-raw FILE.zip` against vncev, which uses auth None."""

    def setUp(self) -> None:
        if not port_open(HOST, VNCEV.port):
            self.skipTest(
                f"vncev not reachable on {HOST}:{VNCEV.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture = Path(tempfile.mkdtemp()) / "capture.zip"
        self.proxy = _start_vnclog(CAPTURE_PROXY_PORT, f"{HOST}::{VNCEV.port}", self.capture)

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
                "vnclog",
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

    The unit tests scrub a scripted challenge/response; only a live run
    proves it against tigervnc's real handshake.
    """

    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC_AUTH.port):
            self.skipTest(
                f"tigervnc-auth not reachable on {HOST}:{TIGERVNC_AUTH.port} -- "
                "start the servers first with `make servers-up`"
            )
        self.capture = Path(tempfile.mkdtemp()) / "capture.zip"
        self.proxy = _start_vnclog(CAPTURE_AUTH_PROXY_PORT, f"{HOST}::{TIGERVNC_AUTH.port}", self.capture)

    def tearDown(self) -> None:
        _stop_proxy(self.proxy)

    def test_capture_scrubs_vnc_auth_challenge_and_response(self) -> None:
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

        # More than the handshake: post-auth client traffic proves nothing
        # truncated the recording at the auth exchange.
        HANDSHAKE_ONLY = 12 + 1 + 16
        self.assertGreater(
            len(c2s), HANDSHAKE_ONLY, f"c2s.bin looks truncated at the handshake: {len(c2s)} bytes: {c2s!r}"
        )

        # The challenge sits at a fixed offset too: 12-byte greeting, the
        # count of security types, the one type on offer, then the 16 bytes
        # that must have been zeroed.
        self.assertEqual(s2c[14:30], bytes(16), f"auth challenge was not scrubbed: {s2c[:32]!r}")

        # The response sits at a fixed offset on the 3.8 path: 12-byte
        # version reply, 1-byte security type, then the 16 bytes that must
        # have been zeroed.
        self.assertEqual(c2s[13:29], bytes(16), f"auth response was not scrubbed: {c2s[:32]!r}")
        self.assertIsNone(meta.get("unscrubbable_auth"))

        self.assertIn("keydown z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
        self.assertIn("keyup z", session_vdo, f"vnclog recorded:\n{session_vdo!r}")
