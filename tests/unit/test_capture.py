"""Unit coverage for the vnclog --capture kit.

Drives HandshakeScrubber/CaptureWriter directly, and the two proxy protocol
classes through a scripted handshake on mocked transports, so both raw
streams and the challenge/response scrub are covered without a reactor.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from unittest import TestCase, mock

from vncdotool.capture import CaptureWriter, HandshakeScrubber, check_capture_dir, scrub_password, write_meta
from vncdotool.const import AuthTypes
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

        self.assertEqual(s.scrubbed, ["vnc-auth-challenge", "vnc-auth-response"])
        self.assertEqual(s.security_type, AuthTypes.VNC_AUTHENTICATION)
        self.assertEqual(s.protocol_version, "RFB 003.003")
        self.assertEqual(s.security_types, [AuthTypes.VNC_AUTHENTICATION])
        self.assertIsNone(s.unscrubbed_auth)

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
        self.assertEqual(s.scrubbed, ["vnc-auth-challenge", "vnc-auth-response"])
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

        self.assertEqual(s.scrubbed, ["vnc-auth-challenge", "vnc-auth-response"])
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
        self.assertEqual(s.scrubbed, ["vnc-auth-challenge", "vnc-auth-response"])

    def test_auth_none_untouched(self) -> None:
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.NONE]))
        out = s.feed("c2s", bytes([AuthTypes.NONE]))
        self.assertEqual(out, bytes([AuthTypes.NONE]))
        self.assertEqual(s.scrubbed, [])
        self.assertEqual(s.security_type, AuthTypes.NONE)
        self.assertIsNone(s.unscrubbed_auth)

        # security-result(4) + ClientInit(1) + ServerInit(24), still passthrough
        self.assertEqual(s.feed("s2c", SECURITY_RESULT_OK), SECURITY_RESULT_OK)
        self.assertEqual(s.feed("c2s", b"\x01"), b"\x01")
        self.assertEqual(s.feed("s2c", SERVER_INIT_640x480), SERVER_INIT_640x480)
        self.assertEqual(s.width, 640)
        self.assertEqual(s.height, 480)

        rest = b"some-server-name-bytes"
        self.assertEqual(s.feed("s2c", rest), rest)

    def test_unscrubbed_auth_type_is_named(self) -> None:
        """ARD's key exchange passes through verbatim, so it has to be named
        rather than leave `scrubbed` empty and read as "nothing sensitive".
        """
        s = HandshakeScrubber()
        s.feed("s2c", VERSION_38)
        s.feed("c2s", VERSION_38)
        s.feed("s2c", bytes([1, AuthTypes.DIFFIE_HELLMAN]))
        s.feed("c2s", bytes([AuthTypes.DIFFIE_HELLMAN]))

        self.assertEqual(s.scrubbed, [])
        self.assertEqual(s.security_type, AuthTypes.DIFFIE_HELLMAN)
        self.assertIsNotNone(s.unscrubbed_auth)
        self.assertIn("diffie-hellman", s.unscrubbed_auth)
        self.assertIn("30", s.unscrubbed_auth)

        # the DH key material is NOT redacted -- passes straight through
        dh_params = b"\x00\x02\x00\x08" + b"P" * 8 + b"G" * 8
        self.assertEqual(s.feed("s2c", dh_params), dh_params)

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
        self.assertEqual(s.scrubbed, ["vnc-auth-challenge"])

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


class TestScrubPassword(TestCase):
    def test_redacts_password_bytes(self) -> None:
        out, hit = scrub_password(b"xxsecretxx", b"secret")
        self.assertTrue(hit)
        self.assertEqual(out, b"xx" + b"\x00" * 6 + b"xx")

    def test_no_password_configured(self) -> None:
        out, hit = scrub_password(b"whatever", None)
        self.assertFalse(hit)
        self.assertEqual(out, b"whatever")

    def test_password_not_present(self) -> None:
        out, hit = scrub_password(b"whatever", b"missing")
        self.assertFalse(hit)
        self.assertEqual(out, b"whatever")


class TestCheckCaptureDir(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_does_not_create_missing_dir(self) -> None:
        """Validation only: creating the directory is the CLI's job."""
        target = os.path.join(self.tmp, "capture")
        check_capture_dir(target)  # must not raise
        self.assertFalse(os.path.exists(target))

    def test_accepts_existing_empty_dir(self) -> None:
        target = os.path.join(self.tmp, "capture")
        os.makedirs(target)
        check_capture_dir(target)  # must not raise

    def test_refuses_nonempty_dir(self) -> None:
        target = os.path.join(self.tmp, "capture")
        os.makedirs(target)
        with open(os.path.join(target, "stray.txt"), "w") as fh:
            fh.write("x")
        with self.assertRaises(ValueError):
            check_capture_dir(target)

    def test_refuses_non_directory(self) -> None:
        target = os.path.join(self.tmp, "notadir")
        with open(target, "w") as fh:
            fh.write("x")
        with self.assertRaises(ValueError):
            check_capture_dir(target)


class TestCaptureWriter(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_meta_and_write_vnc_auth(self) -> None:
        cw = CaptureWriter(server="host::5900", password=None)
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
        self.assertEqual(cw.scrubbed_list(), ["vnc-auth-challenge", "vnc-auth-response"])

        cw.write(self.tmp)
        write_meta(os.path.join(self.tmp, "meta.json"), cw.meta("9.9.9"))

        with open(os.path.join(self.tmp, "s2c.bin"), "rb") as fh:
            self.assertEqual(fh.read(), bytes(cw.s2c))
        with open(os.path.join(self.tmp, "c2s.bin"), "rb") as fh:
            self.assertEqual(fh.read(), bytes(cw.c2s))

        with open(os.path.join(self.tmp, "meta.json")) as fh:
            meta = json.load(fh)
        self.assertEqual(meta["server"], "host::5900")
        self.assertEqual(meta["vncdotool_version"], "9.9.9")
        self.assertEqual(meta["protocol_version"], "RFB 003.003")
        self.assertEqual(meta["security_types"], [AuthTypes.VNC_AUTHENTICATION])
        self.assertEqual(meta["scrubbed"], ["vnc-auth-challenge", "vnc-auth-response"])
        self.assertIsNone(meta["unscrubbed_auth"])
        self.assertEqual(meta["geometry"], {"width": 640, "height": 480})
        self.assertIn("capture_timestamp", meta)

    def test_auth_none_session_untouched_and_unscrubbed(self) -> None:
        cw = CaptureWriter(server="host::5900", password=None)
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
        self.assertEqual(cw.scrubbed_list(), [])

        cw.write(self.tmp)
        write_meta(os.path.join(self.tmp, "meta.json"), cw.meta("9.9.9"))
        with open(os.path.join(self.tmp, "meta.json")) as fh:
            meta = json.load(fh)
        self.assertEqual(meta["scrubbed"], [])
        self.assertEqual(meta["security_types"], [AuthTypes.NONE])
        self.assertIsNone(meta["unscrubbed_auth"])
        self.assertEqual(meta["geometry"], {"width": 640, "height": 480})

    def test_unscrubbed_auth_recorded_in_meta(self) -> None:
        cw = CaptureWriter(server="host::5900", password=None)
        cw.feed_s2c(VERSION_38)
        cw.feed_c2s(VERSION_38)
        cw.feed_s2c(bytes([1, AuthTypes.DIFFIE_HELLMAN]))
        cw.feed_c2s(bytes([AuthTypes.DIFFIE_HELLMAN]))

        meta = cw.meta("9.9.9")
        self.assertEqual(meta["scrubbed"], [])
        self.assertIsNotNone(meta["unscrubbed_auth"])
        self.assertIn("diffie-hellman", meta["unscrubbed_auth"])

    def test_password_bytes_scrubbed_when_present(self) -> None:
        cw = CaptureWriter(server="host::5900", password=b"hunter2")
        cw.feed_c2s(b"clientcuttext-hunter2-trailing")
        self.assertEqual(bytes(cw.c2s), b"clientcuttext-" + b"\x00" * 7 + b"-trailing")
        self.assertEqual(cw.scrubbed_list(), ["password"])

    def test_write_flushes_pending_non_secret_but_drops_partial_secret(self) -> None:
        cw = CaptureWriter(server="host::5900", password=None)
        cw.feed_s2c(VERSION_33)
        cw.feed_c2s(VERSION_33)
        cw.feed_s2c(b"\x00\x00\x00" + bytes([AuthTypes.VNC_AUTHENTICATION]))
        cw.feed_s2c(CHALLENGE[:6])  # client vanishes mid-challenge

        cw.write(self.tmp)  # simulates connectionLost firing right now

        with open(os.path.join(self.tmp, "s2c.bin"), "rb") as fh:
            s2c = fh.read()
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

        self.server_proxy.capture = CaptureWriter(server="testhost::5900", password=None)

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
        self.assertEqual(sp.capture.scrubbed_list(), ["vnc-auth-challenge", "vnc-auth-response"])

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
        self.assertEqual(sp.capture.scrubbed_list(), ["vnc-auth-challenge", "vnc-auth-response"])

        # ClientInit was reached (not desynced into _handle_protocol on the
        # response bytes), so the client-init handoff fired normally.
        cp.startLogging.assert_called_once_with(sp)

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
        factory.capture_dir = "/tmp/some-capture-dir"
        factory.capture_claimed = True

        sp = VNCLoggingServerProxy()
        sp.factory = factory
        sp.transport = mock.Mock()
        sp.transport.getPeer.return_value = mock.Mock(host="10.0.0.5")

        sp.connectionMade()

        sp.transport.loseConnection.assert_called_once()
        self.assertIsNone(sp.capture)
        factory.getRecorder.assert_not_called()

    def test_empty_connection_does_not_permanently_claim_capture(self) -> None:
        """A bare TCP probe must not lock out the real connection behind it.
        Found live: the functional suite's own port-polling startup wait was
        claiming the capture before vncdo ever connected.
        """
        factory = mock.Mock()
        factory.capture_dir = "/tmp/some-capture-dir"
        factory.capture_claimed = True  # what connectionMade would have set

        probe = VNCLoggingServerProxy()
        probe.factory = factory
        probe.capture = CaptureWriter(server="testhost::5900", password=None)  # never fed any bytes

        probe.connectionLost(mock.Mock())

        self.assertFalse(factory.capture_claimed)
        self.assertIsNone(probe.capture)

    def test_greeting_only_session_is_still_written(self) -> None:
        """A server rejecting the client before it speaks (TigerVNC's "Too
        many security failures" is greeting + reason + close) is a real
        session: the s2c-only capture is written, not discarded as a probe.
        """
        capture_dir = tempfile.mkdtemp()
        factory = mock.Mock()
        factory.capture_dir = capture_dir
        factory.capture_claimed = True

        session = VNCLoggingServerProxy()
        session.factory = factory
        session.capture = CaptureWriter(server="testhost::5900", password=None)
        session.capture.feed_s2c(b"RFB 003.003\n")  # greeting arrived; client never got a byte through

        session.connectionLost(mock.Mock())

        self.assertTrue(factory.capture_claimed, "a real (if one-sided) session keeps the claim")
        with open(os.path.join(capture_dir, "s2c.bin"), "rb") as fh:
            self.assertEqual(fh.read(), b"RFB 003.003\n")
        with open(os.path.join(capture_dir, "c2s.bin"), "rb") as fh:
            self.assertEqual(fh.read(), b"")
        self.assertTrue(os.path.exists(os.path.join(capture_dir, "meta.json")))
