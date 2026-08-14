"""Unit coverage for tests/tools/replay_server.py.

Covers the tool's pure logic -- capture loading, script parsing, the
pacing byte-walk -- with plain bytes and callables; the one socket test
lives in tests/functional/test_replay.py. tests/tools is not a package, so
the module is loaded via importlib from its path.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from struct import pack
from unittest import TestCase

from vncdotool.const import AuthTypes

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = REPO_ROOT / "tests" / "tools" / "replay_server.py"
_spec = importlib.util.spec_from_file_location("replay_server_tool", _TOOL_PATH)
replay_server = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# dataclass() resolves string type hints via sys.modules[cls.__module__],
# so the module has to be registered before it is exec'd.
sys.modules[_spec.name] = replay_server
_spec.loader.exec_module(replay_server)


VERSION_33 = b"RFB 003.003\n"
VERSION_38 = b"RFB 003.008\n"
SERVER_INIT_640x480 = (
    b"\x02\x80\x01\xe0"  # width=640, height=480
    b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
    b"\x00\x00\x00\x00"  # name-len=0
)


class TestLoadCapture(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _archive(self, **members: bytes) -> str:
        path = os.path.join(self.tmp, "capture.zip")
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members.items():
                archive.writestr(name.replace("_", "."), data)
        return path

    def test_loads_s2c_bytes(self) -> None:
        path = self._archive(s2c_bin=b"hello-s2c")

        s2c_data, c2s_data, meta = replay_server.load_capture(path)

        self.assertEqual(s2c_data, b"hello-s2c")
        self.assertIsNone(c2s_data)
        self.assertIsNone(meta)

    def test_loads_c2s_bytes_when_present(self) -> None:
        path = self._archive(s2c_bin=b"x", c2s_bin=b"hello-c2s")

        _, c2s_data, _ = replay_server.load_capture(path)

        self.assertEqual(c2s_data, b"hello-c2s")

    def test_loads_meta_json_when_present(self) -> None:
        path = self._archive(s2c_bin=b"x", meta_json=json.dumps({"server": "host::5900"}).encode())

        _, _, meta = replay_server.load_capture(path)

        self.assertEqual(meta, {"server": "host::5900"})

    def test_missing_s2c_bin_raises(self) -> None:
        path = self._archive(meta_json=b"{}")

        with self.assertRaises(SystemExit):
            replay_server.load_capture(path)

    def test_missing_archive_raises(self) -> None:
        with self.assertRaises(SystemExit):
            replay_server.load_capture(os.path.join(self.tmp, "absent.zip"))

    def test_non_zip_raises_rather_than_traceback(self) -> None:
        """A capture directory from an older vnclog, or any stray file."""
        path = os.path.join(self.tmp, "not-a-zip.zip")
        with open(path, "wb") as fh:
            fh.write(b"not a zip at all")

        with self.assertRaises(SystemExit) as caught:
            replay_server.load_capture(path)

        self.assertIn("--capture-raw", str(caught.exception))


class TestScrubWarnings(TestCase):
    """Warnings come from the security type the capture actually negotiated.

    meta.json lists the types the server *offered*, which does not say which
    one the client chose, so it cannot drive these.
    """

    def test_unknown_security_type_no_warnings(self) -> None:
        self.assertEqual(replay_server.scrub_warnings(None), [])

    def test_auth_none_no_warnings(self) -> None:
        self.assertEqual(replay_server.scrub_warnings(AuthTypes.NONE), [])

    def test_vnc_auth_warns_the_challenge_is_zeroed(self) -> None:
        warnings = replay_server.scrub_warnings(AuthTypes.VNC_AUTHENTICATION)

        self.assertEqual(len(warnings), 1)
        self.assertIn("all-zero", warnings[0])

    def test_ard_warns_the_key_exchange_is_in_the_clear(self) -> None:
        warnings = replay_server.scrub_warnings(AuthTypes.DIFFIE_HELLMAN)

        self.assertEqual(len(warnings), 1)
        self.assertIn("Diffie-Hellman", warnings[0])

    def test_unscrubbable_type_warns_credentials_are_verbatim(self) -> None:
        """Reaching a capture at all means --capture-raw-unsafe-auth was passed."""
        warnings = replay_server.scrub_warnings(AuthTypes.VENCRYPT)

        self.assertEqual(len(warnings), 1)
        self.assertIn("unsafe-auth", warnings[0])


class TestLoadScript(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, source: str) -> str:
        path = os.path.join(self.tmp, "script.py")
        with open(path, "w") as fh:
            fh.write(source)
        return path

    def test_loads_valid_messages(self) -> None:
        path = self._write(
            "MESSAGES = [b'abc', ('wait', 5), ('pause', 0.1), b'def']\n"
        )
        messages = replay_server.load_script(path)
        self.assertEqual(messages, [b"abc", ("wait", 5), ("pause", 0.1), b"def"])

    def test_missing_messages_raises(self) -> None:
        path = self._write("X = 1\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_messages_not_a_list_raises(self) -> None:
        path = self._write("MESSAGES = b'not-a-list'\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_bad_entry_raises(self) -> None:
        path = self._write("MESSAGES = [b'ok', ('bogus', 1)]\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_bad_entry_type_raises(self) -> None:
        path = self._write("MESSAGES = [42]\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_wait_with_non_int_nbytes_raises_at_load_time(self) -> None:
        """A bad payload type must die loudly at startup (SystemExit), not
        as a mid-connection TypeError once a real client is waiting."""
        path = self._write("MESSAGES = [('wait', 'five')]\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_wait_with_float_nbytes_raises(self) -> None:
        path = self._write("MESSAGES = [('wait', 5.5)]\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_pause_with_non_numeric_seconds_raises(self) -> None:
        path = self._write("MESSAGES = [('pause', 'a while')]\n")
        with self.assertRaises(SystemExit):
            replay_server.load_script(path)

    def test_pause_accepts_int_or_float(self) -> None:
        path = self._write("MESSAGES = [('pause', 1), ('pause', 1.5)]\n")
        messages = replay_server.load_script(path)
        self.assertEqual(messages, [("pause", 1), ("pause", 1.5)])

    def test_script_can_compute_messages(self) -> None:
        """Scripts are exec()'d, not just literal-eval'd -- prove arbitrary
        (trusted) Python runs, per the module docstring's "trusted
        developer code" note."""
        path = self._write(
            "def build():\n"
            "    return [bytes([i]) for i in range(3)]\n"
            "MESSAGES = build()\n"
        )
        messages = replay_server.load_script(path)
        self.assertEqual(messages, [b"\x00", b"\x01", b"\x02"])


class TestReplayHandshakePaced(TestCase):
    """Drives replay_handshake_paced() with a fake client: a queue of canned
    c2s replies popped by recv_exact().
    """

    def _run(
        self, s2c_data: bytes, client_replies: list[bytes], recorded_c2s_data: bytes | None = None
    ) -> tuple[bytes, "replay_server.PaceResult"]:
        sent = bytearray()
        replies = list(client_replies)

        def send(data: bytes) -> None:
            sent.extend(data)

        def recv_exact(nbytes: int) -> bytes:
            if not replies:
                return b""
            chunk = replies.pop(0)
            assert len(chunk) == nbytes, f"test client reply {chunk!r} does not match requested {nbytes} bytes"
            return chunk

        result = replay_server.replay_handshake_paced(s2c_data, send, recv_exact, recorded_c2s_data=recorded_c2s_data)
        return bytes(sent), result

    def test_auth_none_pre38_handshake(self) -> None:
        """Pre-3.8 + AuthTypes.NONE: greeting, then straight to the 4-byte
        auth announce (no security-type list), no SecurityResult, then
        ClientInit's 1 byte is awaited before ServerInit is sent."""
        greeting = VERSION_33
        auth_announce = pack("!I", AuthTypes.NONE)
        s2c_data = greeting + auth_announce + SERVER_INIT_640x480 + b"EXTRA-FBU-BYTES"

        sent, result = self._run(
            s2c_data,
            client_replies=[VERSION_33, b"\x01"],  # version reply, then ClientInit shared=1
        )

        self.assertEqual(sent, greeting + auth_announce + SERVER_INIT_640x480)
        self.assertEqual(result.offset, len(greeting) + len(auth_announce) + len(SERVER_INIT_640x480))
        self.assertFalse(result.diverged)
        self.assertEqual(s2c_data[result.offset :], b"EXTRA-FBU-BYTES")

    def test_client_downgrade_still_finds_the_right_shape(self) -> None:
        """A 3.3 reply to a 3.8 greeting must pace down the pre-3.7
        direct-auth path, not the security-type-list path."""
        greeting = b"RFB 003.008\n"
        auth_announce = pack("!I", AuthTypes.NONE)
        s2c_data = greeting + auth_announce + SERVER_INIT_640x480

        sent, result = self._run(
            s2c_data,
            client_replies=[VERSION_33, b"\x01"],
        )

        self.assertEqual(sent, greeting + auth_announce + SERVER_INIT_640x480)
        self.assertEqual(result.offset, len(s2c_data))

    def test_client_disconnects_mid_handshake_stops_pacing(self) -> None:
        """If the fake client never replies (empty recv), pacing must stop
        rather than hang or raise -- the offset reflects only what was
        actually paced out."""
        greeting = VERSION_33
        s2c_data = greeting + pack("!I", AuthTypes.NONE) + SERVER_INIT_640x480

        sent, result = self._run(s2c_data, client_replies=[])  # client vanishes before replying

        self.assertEqual(sent, greeting)
        self.assertEqual(result.offset, len(greeting))

    def test_truncated_capture_stops_pacing_without_raising(self) -> None:
        """A capture with fewer s2c bytes than the handshake grammar wants
        next (a hand-edited or corrupted capture) must not raise -- pacing
        stops with whatever was sent so far."""
        s2c_data = b"RFB 003."  # cut off mid-greeting

        sent, result = self._run(s2c_data, client_replies=[])

        self.assertEqual(sent, b"")
        self.assertEqual(result.offset, 0)

    def test_security_type_divergence_detected_and_bails(self) -> None:
        """Recorded session used VNC_AUTHENTICATION, live client picks NONE
        (e.g. replayed without -p). Pacing must report both types and stop:
        the recorded bytes past this point assume the other path."""
        num_types_and_list = bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])
        s2c_data = (
            VERSION_38
            + num_types_and_list
            + bytes([0]) * 16  # recorded (scrubbed) challenge -- must never be sent
            + b"MORE-BYTES-THAT-MUST-NOT-BE-SENT"
        )
        # What c2s.bin recorded: version reply, then VNC_AUTHENTICATION.
        recorded_c2s_data = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION])

        # The LIVE client instead picks NONE.
        live_replies = [VERSION_38, bytes([AuthTypes.NONE])]

        sent, result = self._run(s2c_data, client_replies=live_replies, recorded_c2s_data=recorded_c2s_data)

        self.assertTrue(result.diverged)
        self.assertEqual(result.recorded_security_type, AuthTypes.VNC_AUTHENTICATION)
        self.assertEqual(result.live_security_type, AuthTypes.NONE)
        # Greeting + security-types list only: the wrong-path challenge
        # bytes must not have gone out.
        self.assertEqual(sent, VERSION_38 + num_types_and_list)
        self.assertEqual(result.offset, len(VERSION_38) + len(num_types_and_list))

    def test_matching_security_type_does_not_diverge(self) -> None:
        """The control case for the divergence check: recorded and live
        both choose VNC_AUTHENTICATION -- pacing proceeds normally and
        `diverged` stays False."""
        num_types_and_list = bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])
        challenge = bytes(range(16))
        s2c_data = VERSION_38 + num_types_and_list + challenge
        recorded_c2s_data = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION])
        live_replies = [VERSION_38, bytes([AuthTypes.VNC_AUTHENTICATION]), bytes(range(200, 216))]

        sent, result = self._run(s2c_data, client_replies=live_replies, recorded_c2s_data=recorded_c2s_data)

        self.assertFalse(result.diverged)
        self.assertEqual(sent, s2c_data)
        self.assertEqual(result.offset, len(s2c_data))

    def test_no_recorded_c2s_data_skips_divergence_check(self) -> None:
        """Without c2s.bin there is nothing to compare against, so pacing
        proceeds and never sets `diverged`."""
        auth_announce = pack("!I", AuthTypes.NONE)
        s2c_data = VERSION_33 + auth_announce + SERVER_INIT_640x480

        sent, result = self._run(s2c_data, client_replies=[VERSION_33, b"\x01"])

        self.assertFalse(result.diverged)
        self.assertEqual(sent, s2c_data)


class TestRecordedSecurityType(TestCase):
    """_recorded_security_type() walks fully-recorded s2c/c2s bytes (no
    live client at all) to learn what a capture's original session
    negotiated -- the other half of the divergence check."""

    def test_pre38_none_from_recorded_bytes(self) -> None:
        s2c_data = VERSION_33 + pack("!I", AuthTypes.NONE)
        c2s_data = VERSION_33

        result = replay_server._recorded_security_type(s2c_data, c2s_data)

        self.assertEqual(result, AuthTypes.NONE)

    def test_negotiated_vnc_auth_from_recorded_bytes(self) -> None:
        s2c_data = VERSION_38 + bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])
        c2s_data = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION])

        result = replay_server._recorded_security_type(s2c_data, c2s_data)

        self.assertEqual(result, AuthTypes.VNC_AUTHENTICATION)

    def test_truncated_recorded_streams_return_none(self) -> None:
        result = replay_server._recorded_security_type(b"RFB 003.", b"")
        self.assertIsNone(result)


class TestClientReaderTimeouts(TestCase):
    """ClientReader's timeout handling. .start() is never called, so the
    buffer never fills and the Condition's wait-timeout logic is what runs."""

    def test_read_exact_times_out_and_warns(self) -> None:
        reader = replay_server.ClientReader(sock=None)

        stderr = io.StringIO()
        start = time.monotonic()
        with redirect_stderr(stderr):
            data = reader.read_exact(10, timeout=0.05)
        elapsed = time.monotonic() - start

        self.assertEqual(data, b"")
        self.assertLess(elapsed, 2.0, "read_exact did not respect its timeout")
        self.assertIn("timed out", stderr.getvalue())
        self.assertIn("10 bytes", stderr.getvalue())

    def test_wait_for_total_times_out_and_warns(self) -> None:
        reader = replay_server.ClientReader(sock=None)

        stderr = io.StringIO()
        start = time.monotonic()
        with redirect_stderr(stderr):
            reached = reader.wait_for_total(10, timeout=0.05)
        elapsed = time.monotonic() - start

        self.assertFalse(reached)
        self.assertLess(elapsed, 2.0, "wait_for_total did not respect its timeout")
        self.assertIn("timed out", stderr.getvalue())

    def test_read_exact_returns_immediately_once_satisfied(self) -> None:
        """A satisfied read returns without waiting: feed the buffer
        directly, bypassing the socket-reading thread."""
        reader = replay_server.ClientReader(sock=None)
        reader._buf += b"0123456789"

        data = reader.read_exact(5, timeout=5)

        self.assertEqual(data, b"01234")
        self.assertEqual(bytes(reader._buf), b"56789")
