"""Unit coverage for the vnclog --capture-raw kit.

Drives HandshakeScrubber/CaptureWriter directly, and the two proxy protocol
classes through a scripted handshake on mocked transports, so both raw
streams and the challenge/response scrub are covered without a reactor.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from struct import pack
from unittest import TestCase, mock

from twisted.protocols import portforward

from vncdotool.client import VNCDoToolClient
from vncdotool.capture import (
    ARD_CREDENTIALS_LEN,
    CaptureWriter,
    HandshakeScrubber,
    check_capture_target,
)
from vncdotool.const import AuthTypes, Encoding
from vncdotool.loggingproxy import VNCLoggingClientProxy, VNCLoggingServerProxy

VERSION_33 = b"RFB 003.003\n"
VERSION_38 = b"RFB 003.008\n"
CHALLENGE = bytes(range(16))
RESPONSE = bytes(range(200, 216))
MARKER = b"\x00" * 16
SECURITY_RESULT_OK = b"\x00\x00\x00\x00"
SERVER_INIT_640x480 = (
    b"\x02\x80\x01\xe0"  # width=640, height=480
    b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
    b"\x00\x00\x00\x00"  # name-len=0
)


class TestHandshakeScrubber(TestCase):
    def test_vnc_auth_scrubbed_pre37(self) -> None:
        s = HandshakeScrubber()
        self.assertEqual(s.feed("s2c", VERSION_33), VERSION_33)
        self.assertEqual(s.feed("c2s", VERSION_33), VERSION_33)
        auth_announce = b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION])
        self.assertEqual(s.feed("s2c", auth_announce), auth_announce)
        self.assertEqual(s.feed("s2c", CHALLENGE), MARKER)
        self.assertEqual(s.feed("c2s", RESPONSE), MARKER)

        self.assertEqual(s.security_type, AuthTypes.VNC_AUTHENTICATION)
        self.assertEqual(s.protocol_version, "RFB 003.003")
        self.assertEqual(s.security_types, [AuthTypes.VNC_AUTHENTICATION])
        self.assertIsNone(s.unscrubbable_auth)

        # the security-result that follows is still passed through untouched
        self.assertEqual(s.feed("s2c", SECURITY_RESULT_OK), SECURITY_RESULT_OK)

    def test_vnc_auth_scrubbed_negotiated(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        # server offers None + VNC auth, client picks VNC auth
        self.assertEqual(
            s.feed("s2c", bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])),
            bytes([2, AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION]),
        )
        self.assertEqual(s.feed("c2s", bytes([AuthTypes.VNC_AUTHENTICATION])), bytes([AuthTypes.VNC_AUTHENTICATION]))
        self.assertEqual(s.feed("s2c", CHALLENGE), MARKER)
        self.assertEqual(s.feed("c2s", RESPONSE), MARKER)
        self.assertEqual(s.security_types, [AuthTypes.NONE, AuthTypes.VNC_AUTHENTICATION])

    def test_version_downgrade_still_finds_vnc_auth(self) -> None:
        """A 3.3 reply to a 3.8 greeting puts the exchange on the pre-3.7
        direct-auth path. The scrubber must take the same branch or it
        watches the wrong 16 bytes and lets the real ones through.
        """
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)  # server greets 3.8
        s.feed("c2s", VERSION_33)  # client downgrades to 3.3
        self.assertEqual(s.negotiated_version, (3, 3))

        # pre-3.7 path: a direct 4-byte auth type announcement, no
        # client-side security-type selection byte.
        auth_announce = b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION])
        self.assertEqual(s.feed("s2c", auth_announce), auth_announce)
        self.assertEqual(s.feed("s2c", CHALLENGE), MARKER)
        self.assertEqual(s.feed("c2s", RESPONSE), MARKER)

        self.assertEqual(s.security_type, AuthTypes.VNC_AUTHENTICATION)

    def test_downgrade_the_other_way_is_also_followed(self) -> None:
        """A malformed client claiming 3.8 against a 3.3 greeting: track
        what is on the wire rather than assume either side behaves.
        """
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_33)
        s.feed("c2s", VERSION_38)
        self.assertEqual(s.negotiated_version, (3, 8))

        self.assertEqual(s.feed("s2c", bytes([1, AuthTypes.VNC_AUTHENTICATION])), bytes([1, AuthTypes.VNC_AUTHENTICATION]))
        self.assertEqual(s.feed("c2s", bytes([AuthTypes.VNC_AUTHENTICATION])), bytes([AuthTypes.VNC_AUTHENTICATION]))
        self.assertEqual(s.feed("s2c", CHALLENGE), MARKER)
        self.assertEqual(s.feed("c2s", RESPONSE), MARKER)

    def test_auth_none_untouched(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.NONE]))
        out = s.feed("c2s", bytes([AuthTypes.NONE]))
        self.assertEqual(out, bytes([AuthTypes.NONE]))
        self.assertEqual(s.security_type, AuthTypes.NONE)
        self.assertIsNone(s.unscrubbable_auth)

        # security-result(4) + ClientInit(1) + ServerInit(24), still passthrough
        self.assertEqual(s.feed("s2c", SECURITY_RESULT_OK), SECURITY_RESULT_OK)
        self.assertEqual(s.feed("c2s", b"\x01"), b"\x01")
        self.assertEqual(s.feed("s2c", SERVER_INIT_640x480), SERVER_INIT_640x480)
        self.assertEqual(s.width, 640)
        self.assertEqual(s.height, 480)

        rest = b"some-server-name-bytes"
        self.assertEqual(s.feed("s2c", rest), rest)

    def _ard_to_credentials(self, s: HandshakeScrubber, key_len: int = 8) -> None:
        """Drive an ARD handshake up to the client's credential block."""
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.DIFFIE_HELLMAN]))
        s.feed("c2s", bytes([AuthTypes.DIFFIE_HELLMAN]))
        self.dh_params = b"\x00\x02" + key_len.to_bytes(2, "big")
        self.modulus = b"P" * key_len
        self.server_key = b"G" * key_len

    def test_ard_credentials_scrubbed_key_exchange_kept(self) -> None:
        """The AES block carrying username+password goes; the DH values stay.

        Keeping the exchange is deliberate: ARD compatibility bugs live in
        those values, and they are public by construction.
        """
        s = HandshakeScrubber()
        self._ard_to_credentials(s)

        self.assertEqual(s.feed("s2c", self.dh_params), self.dh_params)
        self.assertEqual(s.feed("s2c", self.modulus), self.modulus)
        self.assertEqual(s.feed("s2c", self.server_key), self.server_key)

        credentials = bytes(range(256))[:ARD_CREDENTIALS_LEN]
        client_key = b"Y" * 8
        self.assertEqual(s.feed("c2s", credentials + client_key), bytes(ARD_CREDENTIALS_LEN) + client_key)

        self.assertIsNone(s.unscrubbable_auth)
        self.assertIsNone(s.abort_reason)
        self.assertEqual(s.feed("s2c", SECURITY_RESULT_OK), SECURITY_RESULT_OK)

    def test_scrubbing_preserves_byte_offsets(self) -> None:
        """A redaction that changed length would break replay of the capture."""
        s = HandshakeScrubber()
        self._ard_to_credentials(s)
        s.feed("s2c", self.dh_params + self.modulus + self.server_key)

        credentials = b"\xab" * ARD_CREDENTIALS_LEN
        out = s.feed("c2s", credentials)
        self.assertEqual(len(out), ARD_CREDENTIALS_LEN)
        self.assertNotIn(b"\xab", out)

    def test_unscrubbable_auth_aborts_by_default(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.TIGHT]))
        s.feed("c2s", bytes([AuthTypes.TIGHT]))

        self.assertIsNotNone(s.abort_reason)
        self.assertIn("tight", s.abort_reason)
        self.assertIn("--capture-raw-unsafe-auth", s.abort_reason)
        self.assertIn("tight", s.unscrubbable_auth)
        self.assertIn("16", s.unscrubbable_auth)

    def test_unscrubbable_auth_allowed_when_opted_in(self) -> None:
        s = HandshakeScrubber(allow_unsafe_auth=True)
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.TIGHT]))
        s.feed("c2s", bytes([AuthTypes.TIGHT]))

        self.assertIsNone(s.abort_reason)
        self.assertIn("tight", s.unscrubbable_auth)
        # key exchange passes through verbatim -- that is what was opted into
        exchange = b"\x01\x02\x03\x04"
        self.assertEqual(s.feed("s2c", exchange), exchange)

    def test_split_across_chunks(self) -> None:
        s = HandshakeScrubber()
        self.assertEqual(s.feed("s2c", b"RFB 003."), b"")
        self.assertEqual(s.feed("s2c", b"003\n"), VERSION_33)

    def test_split_challenge_across_chunks(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_33)
        s.feed("c2s", VERSION_33)
        s.feed("s2c", b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        first = s.feed("s2c", CHALLENGE[:6])
        second = s.feed("s2c", CHALLENGE[6:])
        self.assertEqual(first, b"")
        self.assertEqual(second, MARKER)

    def test_flush_drops_partial_secret(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_33)
        s.feed("c2s", VERSION_33)
        s.feed("s2c", b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        s.feed("s2c", CHALLENGE[:6])  # connection drops mid-challenge

        pending = s.flush()
        self.assertEqual(pending["s2c"], b"", "a half-collected secret must never be flushed in the clear")
        self.assertEqual(pending["c2s"], b"")

    def test_flush_emits_pending_non_secret(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_33)
        s.feed("c2s", VERSION_33)
        s.feed("s2c", b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        s.feed("s2c", CHALLENGE)
        s.feed("c2s", RESPONSE)
        s.feed("s2c", SECURITY_RESULT_OK[:2])  # connection drops mid-result, not a secret

        pending = s.flush()
        self.assertEqual(pending["s2c"], SECURITY_RESULT_OK[:2])
        self.assertEqual(pending["c2s"], b"")


class TestCheckCaptureTarget(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_accepts_missing_zip_and_creates_nothing(self) -> None:
        """Validation only: the archive is written when the session ends."""
        target = os.path.join(self.tmp, "capture.zip")
        check_capture_target(target)  # must not raise
        self.assertFalse(os.path.exists(target))

    def test_refuses_non_zip_suffix(self) -> None:
        with self.assertRaises(ValueError):
            check_capture_target(os.path.join(self.tmp, "capture"))

    def test_refuses_existing_file(self) -> None:
        target = os.path.join(self.tmp, "capture.zip")
        with open(target, "w") as fh:
            fh.write("x")
        with self.assertRaises(ValueError):
            check_capture_target(target)

    def test_refuses_missing_parent_directory(self) -> None:
        with self.assertRaises(ValueError):
            check_capture_target(os.path.join(self.tmp, "nope", "capture.zip"))


class TestCaptureWriter(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.archive = os.path.join(self.tmp, "capture.zip")

    def read_archive(self, name: str) -> bytes:
        with zipfile.ZipFile(self.archive) as zf:
            return zf.read(name)

    def read_meta(self) -> dict:
        return json.loads(self.read_archive("meta.json"))

    def test_meta_and_write_vnc_auth(self) -> None:
        cw = CaptureWriter(server="host::5900")
        cw.feed_s2c(VERSION_33)
        cw.feed_c2s(VERSION_33)
        cw.feed_s2c(b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        cw.feed_s2c(CHALLENGE)
        cw.feed_c2s(RESPONSE)
        cw.feed_s2c(SECURITY_RESULT_OK)
        cw.feed_c2s(b"\x01")
        cw.feed_s2c(SERVER_INIT_640x480)

        expected_s2c = (
            VERSION_33
            + b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION])
            + MARKER
            + SECURITY_RESULT_OK
            + SERVER_INIT_640x480
        )
        self.assertEqual(bytes(cw.s2c), expected_s2c)
        self.assertEqual(bytes(cw.c2s), VERSION_33 + MARKER + b"\x01")

        cw.write_archive(self.archive, cw.meta("9.9.9"), session_vdo=b"pause 0.1 key a\n")

        with zipfile.ZipFile(self.archive) as zf:
            self.assertEqual(
                sorted(zf.namelist()), ["c2s.bin", "meta.json", "s2c.bin", "session.vdo"]
            )
        self.assertEqual(self.read_archive("s2c.bin"), bytes(cw.s2c))
        self.assertEqual(self.read_archive("c2s.bin"), bytes(cw.c2s))
        self.assertEqual(self.read_archive("session.vdo"), b"pause 0.1 key a\n")

        meta = self.read_meta()
        self.assertEqual(meta["server"], "host::5900")
        self.assertEqual(meta["vncdotool_version"], "9.9.9")
        self.assertEqual(meta["protocol_version"], "RFB 003.003")
        self.assertEqual(meta["security_types"], [AuthTypes.VNC_AUTHENTICATION])
        self.assertEqual(meta["geometry"], {"width": 640, "height": 480})
        self.assertIn("capture_timestamp", meta)

    def test_auth_none_session_untouched_and_unscrubbed(self) -> None:
        cw = CaptureWriter(server="host::5900")
        cw.feed_s2c(VERSION_38)
        cw.feed_c2s(VERSION_38)
        cw.feed_s2c(bytes([1, AuthTypes.NONE]))
        cw.feed_c2s(bytes([AuthTypes.NONE]))
        cw.feed_s2c(SECURITY_RESULT_OK)
        cw.feed_c2s(b"\x01")
        cw.feed_s2c(SERVER_INIT_640x480)

        self.assertEqual(
            bytes(cw.s2c),
            VERSION_38 + bytes([1, AuthTypes.NONE]) + SECURITY_RESULT_OK + SERVER_INIT_640x480,
        )
        self.assertEqual(bytes(cw.c2s), VERSION_38 + bytes([AuthTypes.NONE]) + b"\x01")

        cw.write_archive(self.archive, cw.meta("9.9.9"))
        meta = self.read_meta()
        self.assertEqual(meta["security_types"], [AuthTypes.NONE])
        self.assertEqual(meta["geometry"], {"width": 640, "height": 480})

    def test_unscrubbable_auth_captured_when_opted_in(self) -> None:
        cw = CaptureWriter(
            server="host::5900",
            scrubber=HandshakeScrubber(allow_unsafe_auth=True),
        )
        cw.feed_s2c(VERSION_38)
        cw.feed_c2s(VERSION_38)
        cw.feed_s2c(bytes([1, AuthTypes.TIGHT]))
        cw.feed_c2s(bytes([AuthTypes.TIGHT]))

        self.assertIsNone(cw.abort_reason, "the opt-in must not abort")
        self.assertIn("tight", cw.scrubber.unscrubbable_auth)

    def test_encodings_seen_recorded_in_meta(self) -> None:
        """What the server actually sent, named where we know the name."""
        cw = CaptureWriter(server="host::5900")
        cw.note_encoding(Encoding.RAW)
        cw.note_encoding(Encoding.RAW)
        cw.note_encoding(Encoding.ZRLE)
        cw.note_encoding(12345)  # a server sending something we do not know

        self.assertEqual(
            cw.meta("9.9.9")["encodings_seen"],
            [
                {"encoding": int(Encoding.RAW), "name": "raw", "rectangles": 2},
                {"encoding": int(Encoding.ZRLE), "name": "zrle", "rectangles": 1},
                {"encoding": 12345, "name": None, "rectangles": 1},
            ],
        )

    def test_no_partial_archive_left_when_write_fails(self) -> None:
        cw = CaptureWriter(server="host::5900")
        cw.feed_s2c(VERSION_33)
        with mock.patch("vncdotool.capture.json.dumps", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cw.write_archive(self.archive, cw.meta("9.9.9"))

        self.assertFalse(os.path.exists(self.archive))
        self.assertFalse(os.path.exists(self.archive + ".part"))

    def test_write_flushes_pending_non_secret_but_drops_partial_secret(self) -> None:
        cw = CaptureWriter(server="host::5900")
        cw.feed_s2c(VERSION_33)
        cw.feed_c2s(VERSION_33)
        cw.feed_s2c(b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        cw.feed_s2c(CHALLENGE[:6])  # client vanishes mid-challenge

        cw.write_archive(self.archive, cw.meta("9.9.9"))  # connectionLost fires right now

        s2c = self.read_archive("s2c.bin")
        # the 6 partial challenge bytes must never land on disk
        self.assertNotIn(CHALLENGE[:6], s2c)
        self.assertEqual(s2c, VERSION_33 + b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))


class TestProxyCaptureWiring(TestCase):
    """Drive both proxy halves directly, with mocked transports standing in
    for the peer connections portforward would otherwise wire up.
    """

    def setUp(self) -> None:
        self.server_proxy = VNCLoggingServerProxy()
        self.server_proxy.transport = mock.Mock()
        self.server_proxy.buffer = bytearray()
        self.server_proxy._handler = (self.server_proxy._handle_version, 12)
        self.server_proxy.recorder = mock.Mock()

        self.client_proxy = VNCLoggingClientProxy()
        self.client_proxy.transport = mock.Mock()
        # startLogging drags in the whole VNCDoToolClient/recorder machinery,
        # which is exercised elsewhere (test_client.py); stub it out here so
        # this test stays focused on the capture tap.
        self.client_proxy.startLogging = mock.Mock()  # type: ignore[method-assign]

        self.server_proxy.peer = self.client_proxy
        self.client_proxy.peer = self.server_proxy

        factory = mock.Mock()
        factory.password_required = True  # matches the RFB 3.3 script below
        self.server_proxy.factory = factory

        self.server_proxy.capture = CaptureWriter(server="testhost::5900")

    def test_vnc_auth_challenge_and_response_scrubbed_both_directions(self) -> None:
        sp, cp = self.server_proxy, self.client_proxy

        cp.dataReceived(VERSION_33)  # server's greeting, relayed to the real client
        sp.dataReceived(VERSION_33)  # real client's version reply
        cp.dataReceived(b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        cp.dataReceived(CHALLENGE)
        sp.dataReceived(RESPONSE)  # RFBServer's password_required/3.3 path expects exactly this
        cp.dataReceived(b"\x00\x00\x00\x00")  # auth OK
        sp.dataReceived(b"\x01")  # clientInit shared=1

        expected_s2c = VERSION_33 + b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]) + MARKER + b"\x00\x00\x00\x00"
        expected_c2s = VERSION_33 + MARKER + b"\x01"
        self.assertEqual(bytes(sp.capture.s2c), expected_s2c)
        self.assertEqual(bytes(sp.capture.c2s), expected_c2s)

        # Unscrubbed bytes still reach the peer transports: capture must
        # never mutate what the proxy forwards.
        sp.transport.write.assert_any_call(VERSION_33)
        cp.transport.write.assert_any_call(RESPONSE)

        # the client-init handoff still happened
        cp.startLogging.assert_called_once_with(sp)

    def test_no_capture_configured_is_a_no_op(self) -> None:
        sp, cp = self.server_proxy, self.client_proxy
        sp.capture = None

        # should not raise even though nothing is listening for bytes
        cp.dataReceived(VERSION_33)
        sp.dataReceived(VERSION_33)

    def test_vnc_auth_over_negotiated_security_does_not_desync_rfbserver(self) -> None:
        """_handle_security used to jump from the security-type selection
        straight to ClientInit without skipping the 16-byte VNC-auth
        response, desyncing everything after it. Asserts the fix: ClientInit
        is reached cleanly and startLogging fires.
        """
        sp, cp = self.server_proxy, self.client_proxy
        sp.factory.password_required = False  # force the 3.7+ security-byte path

        cp.dataReceived(VERSION_38)
        sp.dataReceived(VERSION_38)
        cp.dataReceived(bytes([1, AuthTypes.VNC_AUTHENTICATION]))
        sp.dataReceived(bytes([AuthTypes.VNC_AUTHENTICATION]))
        cp.dataReceived(CHALLENGE)
        sp.dataReceived(RESPONSE)  # now correctly consumed as the auth response, not `shared`
        cp.dataReceived(b"\x00\x00\x00\x00")  # security result OK
        sp.dataReceived(b"\x01")  # ClientInit: shared=1, reached cleanly this time

        expected_c2s = VERSION_38 + bytes([AuthTypes.VNC_AUTHENTICATION]) + MARKER + b"\x01"
        self.assertEqual(bytes(sp.capture.c2s), expected_c2s)
        expected_s2c = VERSION_38 + bytes([1, AuthTypes.VNC_AUTHENTICATION]) + MARKER + b"\x00\x00\x00\x00"
        self.assertEqual(bytes(sp.capture.s2c), expected_s2c)

        # ClientInit was reached (not desynced into _handle_protocol on the
        # response bytes), so the client-init handoff fired normally.
        cp.startLogging.assert_called_once_with(sp)

    def test_unscrubbable_auth_aborts_and_writes_nothing(self) -> None:
        """Chosen on the client side (3.7+), so it surfaces in the c2s tap."""
        sp, cp = self.server_proxy, self.client_proxy
        sp.factory.capture_path = os.path.join(tempfile.mkdtemp(), "capture.zip")
        sp.factory.session_taken = True

        cp.dataReceived(VERSION_38)
        sp.dataReceived(VERSION_38)
        cp.dataReceived(bytes([1, AuthTypes.TIGHT]))
        sp.dataReceived(bytes([AuthTypes.TIGHT]))

        self.assertIsNone(sp.capture, "the capture must be dropped, not written")
        sp.transport.loseConnection.assert_called_once()
        self.assertFalse(os.path.exists(sp.factory.capture_path))

    def test_unscrubbable_auth_chosen_by_a_pre37_server_also_aborts(self) -> None:
        """Pre-3.7 the server dictates the type, so the s2c tap has to catch it."""
        sp, cp = self.server_proxy, self.client_proxy
        sp.factory.capture_path = os.path.join(tempfile.mkdtemp(), "capture.zip")

        cp.dataReceived(VERSION_33)
        sp.dataReceived(VERSION_33)
        cp.dataReceived(b"\x00\x00\x00" + bytes([AuthTypes.TIGHT]))

        self.assertIsNone(sp.capture)
        sp.transport.loseConnection.assert_called_once()
        self.assertFalse(os.path.exists(sp.factory.capture_path))

    def test_encodings_are_tallied_from_what_the_server_sent(self) -> None:
        """Not from SetEncodings: a server may answer in anything it likes."""
        from vncdotool.loggingproxy import VNCLoggingClient

        capture = CaptureWriter(server="testhost::5900")
        vnclog = VNCLoggingClient()
        vnclog.capture = capture
        # Stop after the tally; the decode path itself is test_client.py's job.
        with mock.patch.object(VNCDoToolClient, "_handleRectangle"):
            for encoding in (Encoding.ZRLE, Encoding.ZRLE, Encoding.HEXTILE):
                vnclog._handleRectangle(pack("!HHHHi", 0, 0, 4, 4, int(encoding)))

        self.assertEqual(
            capture.encodings_seen,
            {int(Encoding.ZRLE): 2, int(Encoding.HEXTILE): 1},
        )

    def test_forwarding_failures_are_not_swallowed(self) -> None:
        """Only the observers are wrapped.

        Suppressing a forwarding failure would leave the client waiting on
        bytes that never arrive, so the session has to fail as it always did.
        """
        sp = self.server_proxy
        sp.factory.password_required = False
        with mock.patch.object(portforward.ProxyServer, "dataReceived", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                sp.dataReceived(VERSION_38)

    def test_capture_survives_a_parser_that_raises(self) -> None:
        """The tap must not depend on RFBServer's semantic parser: an
        unknown ptype raises ProtocolError, and capture and forwarding both
        have to survive it.
        """
        sp, cp = self.server_proxy, self.client_proxy
        sp.factory.password_required = False

        cp.dataReceived(VERSION_38)
        sp.dataReceived(VERSION_38)
        cp.dataReceived(bytes([1, AuthTypes.NONE]))
        sp.dataReceived(bytes([AuthTypes.NONE]))
        sp.dataReceived(b"\x01")  # ClientInit: shared=1

        garbage = bytes([250])  # not a recognised MsgC2S value
        sp.dataReceived(garbage)  # RFBServer._handle_protocol raises ProtocolError(250) here

        expected_c2s = VERSION_38 + bytes([AuthTypes.NONE]) + b"\x01" + garbage
        self.assertEqual(bytes(sp.capture.c2s), expected_c2s)

        # forwarding still happened despite the parser raising
        cp.transport.write.assert_any_call(garbage)

    def test_second_connection_refused_when_capture_already_claimed(self) -> None:
        """One session per directory: a second connection is refused rather
        than clobbering the capture, without reaching connectionMade's
        reactor.connectTCP half.
        """
        factory = mock.Mock()
        factory.capture_path = "/tmp/some-capture.zip"
        factory.session_taken = True

        sp = VNCLoggingServerProxy()
        sp.factory = factory
        sp.transport = mock.Mock()
        sp.transport.getPeer.return_value = mock.Mock(host="10.0.0.5")

        sp.connectionMade()

        sp.transport.loseConnection.assert_called_once()
        self.assertIsNone(sp.capture)
        factory.getRecorder.assert_not_called()

    def test_empty_connection_does_not_use_up_the_one_shot(self) -> None:
        """A bare TCP probe must not lock out the real connection behind it.
        Found live: the functional suite's own port-polling startup wait was
        taking the session before vncdo ever connected.
        """
        factory = mock.Mock()
        factory.one_shot = True
        factory.capture_path = "/tmp/some-capture.zip"
        factory.session_taken = True  # what connectionMade would have set

        probe = VNCLoggingServerProxy()
        probe.factory = factory
        probe.capture = CaptureWriter(server="testhost::5900")  # never fed any bytes

        probe.connectionLost(mock.Mock())

        self.assertFalse(factory.session_taken)
        self.assertIsNone(probe.capture)
        factory.sessionFinished.assert_not_called()

    def test_greeting_only_session_is_still_written(self) -> None:
        """A server rejecting the client before it speaks (TigerVNC's "Too
        many security failures" is greeting + reason + close) is a real
        session: the s2c-only capture is written, not discarded as a probe.
        """
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        archive = os.path.join(tmp, "capture.zip")
        factory = mock.Mock()
        factory.one_shot = True
        factory.capture_path = archive
        factory.session_taken = True
        factory.getRecordedSession.return_value = b""

        session = VNCLoggingServerProxy()
        session.factory = factory
        session.capture = CaptureWriter(server="testhost::5900")
        session.saw_bytes = True  # the greeting arrived
        session.capture.feed_s2c(b"RFB 003.003\n")  # client never got a byte through

        session.connectionLost(mock.Mock())

        self.assertTrue(factory.session_taken, "a real (if one-sided) session is still a session")
        factory.sessionFinished.assert_called_once()
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(zf.read("s2c.bin"), b"RFB 003.003\n")
            self.assertEqual(zf.read("c2s.bin"), b"")
            self.assertIn("meta.json", zf.namelist())
