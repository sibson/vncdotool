"""Unit coverage for tests/tools/replay_capture.py.

tests/tools is not a package, so the module is loaded via importlib from
its path.

`client_timeout=None` throughout: the stall warning is the one thing here
that would put a delayed call on the global reactor.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from struct import pack
from unittest import TestCase, mock

from vncdotool.const import AuthTypes, MsgC2S

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = REPO_ROOT / "tests" / "tools" / "replay_capture.py"
_spec = importlib.util.spec_from_file_location("replay_capture_tool", _TOOL_PATH)
replay_capture = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = replay_capture
_spec.loader.exec_module(replay_capture)


VERSION_33 = b"RFB 003.003\n"
VERSION_38 = b"RFB 003.008\n"
SERVER_INIT_640x480 = (
    b"\x02\x80\x01\xe0"  # width=640, height=480
    b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
    b"\x00\x00\x00\x00"  # name-len=0
)
SESSION = SERVER_INIT_640x480 + b"THE-RECORDED-SESSION"
# What a client sends before a server owes it any framebuffer bytes.
UPDATE_REQUEST = pack("!BBHHHH", MsgC2S.FRAMEBUFFER_UPDATE_REQUEST, 0, 0, 0, 640, 480)

# A 3.8 session that chose VNC auth: greeting, one offered type, the
# scrubbed challenge, SecurityResult, then the session.
VNC_AUTH_S2C = VERSION_38 + bytes([1, AuthTypes.VNC_AUTHENTICATION]) + bytes(16) + pack("!I", 0) + SESSION
VNC_AUTH_C2S = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION]) + bytes(16) + b"\x01"
VNC_AUTH_SESSION_AT = 12 + 2 + 16 + 4

# The pre-3.7 shape: the server picks, and none skips SecurityResult.
NONE_33_S2C = VERSION_33 + pack("!I", AuthTypes.NONE) + SESSION
NONE_33_C2S = VERSION_33 + b"\x01"
NONE_33_SESSION_AT = 12 + 4


def written(protocol) -> bytes:
    """Everything the protocol has sent, in order."""
    return b"".join(call.args[0] for call in protocol.transport.write.call_args_list)


def start(factory) -> replay_capture.ReplayProtocol:
    """Build a protocol on a mocked transport and open the connection."""
    protocol = factory.buildProtocol(("127.0.0.1", 0))
    protocol.transport = mock.Mock()
    protocol.connectionMade()
    return protocol


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
        capture = replay_capture.load_capture(self._archive(s2c_bin=b"hello-s2c"))

        self.assertEqual(capture.s2c, b"hello-s2c")
        self.assertIsNone(capture.c2s)
        self.assertEqual(capture.session_vdo, b"")
        self.assertIsNone(capture.meta)

    def test_loads_c2s_bytes_when_present(self) -> None:
        capture = replay_capture.load_capture(self._archive(s2c_bin=b"x", c2s_bin=b"hello-c2s"))

        self.assertEqual(capture.c2s, b"hello-c2s")

    def test_loads_session_vdo_when_present(self) -> None:
        capture = replay_capture.load_capture(self._archive(s2c_bin=b"x", session_vdo=b"key a\n"))

        self.assertEqual(capture.session_vdo, b"key a\n")

    def test_loads_meta_json_when_present(self) -> None:
        path = self._archive(s2c_bin=b"x", meta_json=json.dumps({"server": "host::5900"}).encode())

        self.assertEqual(replay_capture.load_capture(path).meta, {"server": "host::5900"})

    def test_missing_s2c_bin_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_capture(self._archive(meta_json=b"{}"))

    def test_missing_archive_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_capture(os.path.join(self.tmp, "absent.zip"))

    def test_non_zip_raises_rather_than_traceback(self) -> None:
        path = os.path.join(self.tmp, "not-a-zip.zip")
        with open(path, "wb") as fh:
            fh.write(b"not a zip at all")

        with self.assertRaises(ValueError) as caught:
            replay_capture.load_capture(path)

        self.assertIn("--capture-raw", str(caught.exception))


class TestScrubWarnings(TestCase):
    """Warnings come from the security type the capture actually negotiated.

    meta.json lists the types the server *offered*, which does not say which
    one the client chose, so it cannot drive these.
    """

    def test_unknown_security_type_no_warnings(self) -> None:
        self.assertEqual(replay_capture.scrub_warnings(None), [])

    def test_auth_none_no_warnings(self) -> None:
        self.assertEqual(replay_capture.scrub_warnings(AuthTypes.NONE), [])

    def test_vnc_auth_warns_the_challenge_is_zeroed(self) -> None:
        warnings = replay_capture.scrub_warnings(AuthTypes.VNC_AUTHENTICATION)

        self.assertEqual(len(warnings), 1)
        self.assertIn("all-zero", warnings[0])

    def test_ard_warns_the_key_exchange_is_in_the_clear(self) -> None:
        warnings = replay_capture.scrub_warnings(AuthTypes.DIFFIE_HELLMAN)

        self.assertEqual(len(warnings), 1)
        self.assertIn("Diffie-Hellman", warnings[0])

    def test_unscrubbable_type_warns_credentials_are_verbatim(self) -> None:
        warnings = replay_capture.scrub_warnings(AuthTypes.VENCRYPT)

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
        path = self._write("MESSAGES = [b'abc', ('wait', 5), ('pause', 0.1), b'def']\n")

        messages = replay_capture.load_script(path)

        self.assertEqual(messages, [b"abc", ("wait", 5), ("pause", 0.1), b"def"])

    def test_missing_messages_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("X = 1\n"))

    def test_messages_not_a_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = b'not-a-list'\n"))

    def test_bad_entry_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = [b'ok', ('bogus', 1)]\n"))

    def test_bad_entry_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = [42]\n"))

    def test_wait_with_non_int_nbytes_raises_at_load_time(self) -> None:
        """A bad payload type must die at startup, not as a mid-connection
        TypeError once a real client is waiting."""
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = [('wait', 'five')]\n"))

    def test_wait_with_float_nbytes_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = [('wait', 5.5)]\n"))

    def test_pause_with_non_numeric_seconds_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay_capture.load_script(self._write("MESSAGES = [('pause', 'a while')]\n"))

    def test_pause_accepts_int_or_float(self) -> None:
        path = self._write("MESSAGES = [('pause', 1), ('pause', 1.5)]\n")

        self.assertEqual(replay_capture.load_script(path), [("pause", 1), ("pause", 1.5)])

    def test_script_can_compute_messages(self) -> None:
        """Scripts are exec()'d, not literal-eval'd -- arbitrary (trusted)
        Python runs, per the module docstring."""
        path = self._write(
            "def build():\n"
            "    return [b'x' * 3, ('wait', 2)]\n"
            "MESSAGES = build()\n"
        )

        self.assertEqual(replay_capture.load_script(path), [b"xxx", ("wait", 2)])


class TestReadHandshake(TestCase):
    """Where the recorded handshake ends is what makes skipping it possible."""

    def test_pre38_none(self) -> None:
        handshake = replay_capture.read_handshake(NONE_33_S2C, NONE_33_C2S)

        self.assertEqual(handshake.security_type, AuthTypes.NONE)
        self.assertEqual(handshake.server_init_offset, NONE_33_SESSION_AT)

    def test_negotiated_vnc_auth(self) -> None:
        handshake = replay_capture.read_handshake(VNC_AUTH_S2C, VNC_AUTH_C2S)

        self.assertEqual(handshake.security_type, AuthTypes.VNC_AUTHENTICATION)
        self.assertEqual(handshake.server_init_offset, VNC_AUTH_SESSION_AT)
        self.assertEqual(VNC_AUTH_S2C[handshake.server_init_offset :], SESSION)

    def test_streams_running_out_is_not_an_answer(self) -> None:
        handshake = replay_capture.read_handshake(VERSION_38, b"")

        self.assertIsNone(handshake.security_type)
        self.assertIsNone(handshake.server_init_offset)

    def test_handshake_that_ends_mid_auth_has_no_offset(self) -> None:
        """The security type is known, but where the session starts is not."""
        handshake = replay_capture.read_handshake(
            VERSION_38 + bytes([1, AuthTypes.VNC_AUTHENTICATION]),
            VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION]),
        )

        self.assertEqual(handshake.security_type, AuthTypes.VNC_AUTHENTICATION)
        self.assertIsNone(handshake.server_init_offset)


class TestNegotiatedVersion(TestCase):
    def test_parses_the_client_reply(self) -> None:
        self.assertEqual(replay_capture.negotiated_version(VERSION_38), (3, 8))

    def test_garbage_falls_back_to_33(self) -> None:
        with self.assertLogs(replay_capture.log, "WARNING"):
            self.assertEqual(replay_capture.negotiated_version(b"not a version"), (3, 3))


class TestSawUpdateRequest(TestCase):
    """Stepping over client messages to find the one that asks for a framebuffer."""

    def test_a_request_on_its_own(self) -> None:
        self.assertTrue(replay_capture.saw_update_request(bytearray(UPDATE_REQUEST)))

    def test_events_before_the_request_are_stepped_over(self) -> None:
        buffer = bytearray(
            pack("!BxH", MsgC2S.SET_ENCODING, 2) + pack("!ii", 0, -223)
            + pack("!BBxxI", MsgC2S.KEY_EVENT, 1, 0x61)
            + UPDATE_REQUEST
        )

        self.assertTrue(replay_capture.saw_update_request(buffer))
        self.assertEqual(bytes(buffer), b"")

    def test_a_half_arrived_message_is_left_for_the_next_read(self) -> None:
        buffer = bytearray(UPDATE_REQUEST[:6])

        self.assertFalse(replay_capture.saw_update_request(buffer))
        self.assertEqual(bytes(buffer), UPDATE_REQUEST[:6])

    def test_events_without_a_request_leave_nothing_owed(self) -> None:
        self.assertFalse(
            replay_capture.saw_update_request(bytearray(pack("!BBxxI", MsgC2S.KEY_EVENT, 1, 0x61)))
        )

    def test_an_unmeasurable_message_serves_the_capture_rather_than_stall(self) -> None:
        """Losing the message boundary means never recognising the request, so
        a replay that stopped here would hang instead of showing the bug."""
        with self.assertLogs(replay_capture.log, "WARNING"):
            self.assertTrue(replay_capture.saw_update_request(bytearray([MsgC2S.FILE_TRANSFER, 0])))


class TestNoAuthReplay(TestCase):
    """The recorded auth is replaced by none, so any client can connect."""

    def _factory(self, s2c: bytes, c2s: bytes) -> replay_capture.ReplayFactory:
        factory = replay_capture.ReplayFactory(
            capture=replay_capture.Capture(s2c=s2c, c2s=c2s, session_vdo=b"", meta=None),
            client_timeout=None,
        )
        self.assertFalse(factory.replay_auth, "expected the handshake to be readable")
        return factory

    def test_greeting_goes_out_before_the_client_has_said_anything(self) -> None:
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        self.assertEqual(written(protocol), VERSION_38)

    def test_vnc_auth_capture_replays_as_none_auth(self) -> None:
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(VERSION_38)
        self.assertEqual(written(protocol), VERSION_38 + bytes([1, AuthTypes.NONE]))

        protocol.dataReceived(bytes([AuthTypes.NONE]))
        self.assertEqual(
            written(protocol), VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0)
        )

        protocol.dataReceived(b"\x01")  # ClientInit, shared=1
        self.assertEqual(
            written(protocol),
            VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0) + SERVER_INIT_640x480,
        )

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(
            written(protocol),
            VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0) + SESSION,
        )
        self.assertNotIn(bytes(16), written(protocol), "the scrubbed challenge was served")

    def test_framebuffer_waits_for_the_client_to_ask_for_one(self) -> None:
        """A capture holds one finite recording of the framebuffer, so sending
        it before the client asked means the client that asks a moment later
        waits for an update that already went past it."""
        protocol = start(self._factory(NONE_33_S2C, NONE_33_C2S))

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        self.assertEqual(written(protocol), VERSION_33 + pack("!I", AuthTypes.NONE) + SERVER_INIT_640x480)

        # SetEncodings, which a client sends first and which owes it nothing.
        protocol.dataReceived(pack("!BxH", MsgC2S.SET_ENCODING, 1) + pack("!i", 0))
        self.assertEqual(written(protocol), VERSION_33 + pack("!I", AuthTypes.NONE) + SERVER_INIT_640x480)

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(written(protocol), NONE_33_S2C)

    def test_an_exhausted_capture_leaves_the_connection_to_the_client(self) -> None:
        """Hanging up here would cut short whatever the client is still doing
        with the bytes it has; the original server only closed because its
        own client did."""
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)
        before = written(protocol)
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), before)
        protocol.transport.loseConnection.assert_not_called()

    def test_client_that_never_replies_gets_nothing_past_the_greeting(self) -> None:
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        self.assertEqual(written(protocol), VERSION_38)
        protocol.transport.loseConnection.assert_not_called()

    def test_client_downgrade_takes_the_pre37_shape(self) -> None:
        """A 3.3 reply to a 3.8 greeting: RFC 6143 7.1.1 says the client's
        reply governs, so the server picks the type and there is no
        SecurityResult."""
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), VERSION_38 + pack("!I", AuthTypes.NONE) + SESSION)

    def test_37_client_gets_no_security_result(self) -> None:
        """SecurityResult after a `none` handshake arrived in 3.8."""
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(b"RFB 003.007\n")
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), VERSION_38 + bytes([1, AuthTypes.NONE]) + SESSION)

    def test_client_choosing_a_type_that_was_not_offered_is_carried_on_as_none(self) -> None:
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(VERSION_38)
        with self.assertLogs(replay_capture.log, "WARNING"):
            protocol.dataReceived(bytes([AuthTypes.VNC_AUTHENTICATION]))
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertTrue(written(protocol).endswith(SESSION))


class TestCaptureReplay(TestCase):
    """--replay-auth: the recorded handshake goes out a step at a time."""

    def _factory(self, s2c: bytes, c2s: bytes | None = None, **kwargs) -> replay_capture.ReplayFactory:
        return replay_capture.ReplayFactory(
            capture=replay_capture.Capture(s2c=s2c, c2s=c2s, session_vdo=b"", meta=None),
            replay_auth=True,
            client_timeout=None,
            **kwargs,
        )

    def test_greeting_goes_out_before_the_client_has_said_anything(self) -> None:
        protocol = start(self._factory(NONE_33_S2C))

        self.assertEqual(written(protocol), VERSION_33)

    def test_rest_of_a_pre38_handshake_follows_the_client_reply(self) -> None:
        protocol = start(self._factory(NONE_33_S2C))

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")  # ClientInit, shared=1
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), NONE_33_S2C)

    def test_scrubbed_challenge_is_served_verbatim(self) -> None:
        protocol = start(self._factory(VNC_AUTH_S2C, VNC_AUTH_C2S))

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.VNC_AUTHENTICATION]))

        self.assertIn(bytes(16), written(protocol))

    def test_truncated_capture_sends_what_there_is_and_stops(self) -> None:
        """A hand-edited or corrupted capture must not blow up mid-connection:
        the short remainder goes out and nothing follows it."""
        protocol = start(self._factory(b"RFB 003."))

        self.assertEqual(written(protocol), b"RFB 003.")
        protocol.dataReceived(b"RFB 003.008\n")
        self.assertEqual(written(protocol), b"RFB 003.")

    def test_unreadable_handshake_falls_back_to_verbatim(self) -> None:
        """No c2s.bin means no ServerInit offset, so there is nothing to skip to."""
        factory = replay_capture.ReplayFactory(
            capture=replay_capture.Capture(s2c=NONE_33_S2C, c2s=None, session_vdo=b"", meta=None),
            client_timeout=None,
        )

        self.assertTrue(factory.replay_auth)
        self.assertIsInstance(factory.buildProtocol(None), replay_capture.CaptureReplay)


class TestSecurityTypeDivergence(TestCase):
    """Under --replay-auth, recorded bytes past the security-type choice only
    fit the auth path the original client took; sending them down another
    desyncs it silently.
    """

    def setUp(self) -> None:
        self.offered = bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])
        self.s2c = (
            VERSION_38
            + self.offered
            + bytes(16)  # scrubbed challenge -- must never reach a client on another path
            + b"MORE-BYTES-THAT-MUST-NOT-BE-SENT"
        )
        self.recorded_c2s = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION])

    def _protocol(self, c2s: bytes | None):
        return start(
            replay_capture.ReplayFactory(
                capture=replay_capture.Capture(s2c=self.s2c, c2s=c2s, session_vdo=b"", meta=None),
                replay_auth=True,
                client_timeout=None,
            )
        )

    def test_divergence_closes_the_connection_before_the_challenge(self) -> None:
        protocol = self._protocol(self.recorded_c2s)

        protocol.dataReceived(VERSION_38)
        with self.assertLogs(replay_capture.log, "ERROR") as logged:
            protocol.dataReceived(bytes([AuthTypes.NONE]))

        self.assertEqual(written(protocol), VERSION_38 + self.offered)
        protocol.transport.loseConnection.assert_called_once()
        self.assertIn("divergence", logged.output[0])

    def test_matching_security_type_does_not_diverge(self) -> None:
        protocol = self._protocol(self.recorded_c2s)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.VNC_AUTHENTICATION]))

        self.assertIn(bytes(16), written(protocol))

    def test_without_recorded_c2s_there_is_nothing_to_compare(self) -> None:
        """No c2s.bin means no divergence check, so the same mismatch that
        closes the connection above carries on regardless."""
        protocol = self._protocol(None)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))

        self.assertGreater(len(written(protocol)), len(VERSION_38 + self.offered))
        protocol.transport.loseConnection.assert_not_called()


class TestClientScript(TestCase):
    """The forked vncdo runs the capture's own session, then leaves evidence."""

    def test_recorded_session_is_followed_by_a_screenshot(self) -> None:
        script = replay_capture.client_script(b"key a\nkeyup a\n", "out.png")

        self.assertEqual(script, "key a\nkeyup a\ncapture out.png\n")

    def test_a_capture_with_no_recorded_session_still_screenshots(self) -> None:
        """A GUI-driven capture records events, not vncdo commands, and an
        empty session.vdo must not produce a leading blank line."""
        self.assertEqual(replay_capture.client_script(b"", "out.png"), "capture out.png\n")


class TestScriptReplay(TestCase):
    def _protocol(self, messages: list):
        return start(replay_capture.ReplayFactory(messages=messages, client_timeout=None))

    def test_bytes_are_sent_in_order(self) -> None:
        protocol = self._protocol([b"one", b"two"])

        self.assertEqual(written(protocol), b"onetwo")
        protocol.transport.loseConnection.assert_called_once()

    def test_wait_blocks_until_the_client_has_sent_enough(self) -> None:
        protocol = self._protocol([b"first", ("wait", 4), b"second"])

        self.assertEqual(written(protocol), b"first")

        protocol.dataReceived(b"ab")
        self.assertEqual(written(protocol), b"first")

        protocol.dataReceived(b"cd")
        self.assertEqual(written(protocol), b"firstsecond")

    def test_pause_defers_the_rest_without_blocking(self) -> None:
        with mock.patch.object(replay_capture.reactor, "callLater") as later:
            protocol = self._protocol([b"first", ("pause", 0.5), b"second"])

            self.assertEqual(written(protocol), b"first")
            later.assert_called_once_with(0.5, protocol.advance)

            protocol.advance()

        self.assertEqual(written(protocol), b"firstsecond")
