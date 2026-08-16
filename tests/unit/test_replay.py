"""`client_timeout=None` throughout: the stall warning would touch the reactor."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from struct import pack
from unittest import TestCase, mock

from vncdotool import replay
from vncdotool.const import AuthTypes, MsgC2S, QemuClientMessage

VERSION_33 = b"RFB 003.003\n"
VERSION_38 = b"RFB 003.008\n"
SERVER_INIT_640x480 = (
    b"\x02\x80\x01\xe0"  # width=640, height=480
    b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
    b"\x00\x00\x00\x00"  # name-len=0
)
SERVER_INIT_NAMED = SERVER_INIT_640x480[:-4] + pack("!I", 4) + b"NAME"
FRAMEBUFFER = b"THE-RECORDED-FRAMEBUFFER"
UPDATE_REQUEST = pack("!BBHHHH", MsgC2S.FRAMEBUFFER_UPDATE_REQUEST, 0, 0, 0, 640, 480)

# What a stripped capture holds: a none-auth handshake and then the session.
NONE_38 = VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0) + SERVER_INIT_640x480 + FRAMEBUFFER
NONE_33 = VERSION_33 + pack("!I", AuthTypes.NONE) + SERVER_INIT_640x480 + FRAMEBUFFER
NONE_38_NAMED = VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0) + SERVER_INIT_NAMED + FRAMEBUFFER


def written(protocol) -> bytes:
    return b"".join(call.args[0] for call in protocol.transport.write.call_args_list)


def start(s2c: bytes, meta: dict | None = None, client_timeout: float | None = None, **kwargs) -> replay.ReplayProtocol:
    factory = replay.ReplayFactory(
        capture=replay.Capture(s2c=s2c, session_vdo=b"", meta=meta),
        client_timeout=client_timeout,
        **kwargs,
    )
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
        capture = replay.load_capture(self._archive(s2c_bin=b"hello-s2c"))

        self.assertEqual(capture.s2c, b"hello-s2c")
        self.assertEqual(capture.session_vdo, b"")
        self.assertIsNone(capture.meta)

    def test_loads_session_vdo_when_present(self) -> None:
        capture = replay.load_capture(self._archive(s2c_bin=b"x", session_vdo=b"key a\n"))

        self.assertEqual(capture.session_vdo, b"key a\n")

    def test_loads_meta_json_when_present(self) -> None:
        path = self._archive(s2c_bin=b"x", meta_json=json.dumps({"server": "host::5900"}).encode())

        self.assertEqual(replay.load_capture(path).meta, {"server": "host::5900"})

    def test_preserved_auth_is_read_off_meta(self) -> None:
        stripped = self._archive(s2c_bin=b"x", meta_json=b'{"auth": "stripped"}')
        self.assertFalse(replay.load_capture(stripped).auth_preserved)

        preserved = self._archive(s2c_bin=b"x", meta_json=b'{"auth": "preserved"}')
        self.assertTrue(replay.load_capture(preserved).auth_preserved)

    def test_an_archive_without_meta_is_not_assumed_unsafe(self) -> None:
        self.assertFalse(replay.load_capture(self._archive(s2c_bin=b"x")).auth_preserved)

    def test_missing_s2c_bin_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay.load_capture(self._archive(meta_json=b"{}"))

    def test_missing_archive_raises(self) -> None:
        with self.assertRaises(ValueError):
            replay.load_capture(os.path.join(self.tmp, "absent.zip"))

    def test_non_zip_raises_rather_than_traceback(self) -> None:
        path = os.path.join(self.tmp, "not-a-zip.zip")
        with open(path, "wb") as fh:
            fh.write(b"not a zip at all")

        with self.assertRaises(ValueError) as caught:
            replay.load_capture(path)

        self.assertIn("--capture-raw", str(caught.exception))


class TestSawUpdateRequest(TestCase):
    def test_a_request_on_its_own(self) -> None:
        self.assertTrue(replay.saw_update_request(bytearray(UPDATE_REQUEST)))

    def test_events_before_the_request_are_stepped_over(self) -> None:
        buffer = bytearray(
            pack("!BxH", MsgC2S.SET_ENCODING, 2) + pack("!ii", 0, -223)
            + pack("!BBxxI", MsgC2S.KEY_EVENT, 1, 0x61)
            + UPDATE_REQUEST
        )

        self.assertTrue(replay.saw_update_request(buffer))
        self.assertEqual(bytes(buffer), b"")

    def test_a_half_arrived_message_is_left_for_the_next_read(self) -> None:
        buffer = bytearray(UPDATE_REQUEST[:6])

        self.assertFalse(replay.saw_update_request(buffer))
        self.assertEqual(bytes(buffer), UPDATE_REQUEST[:6])

    def test_events_without_a_request_leave_nothing_owed(self) -> None:
        self.assertFalse(
            replay.saw_update_request(bytearray(pack("!BBxxI", MsgC2S.KEY_EVENT, 1, 0x61)))
        )

    def test_an_unmeasurable_message_serves_the_capture_rather_than_stall(self) -> None:
        """Losing the boundary means never seeing the request, so stopping
        here would hang instead of showing the bug."""
        with self.assertLogs(replay.log, "WARNING"):
            self.assertTrue(replay.saw_update_request(bytearray([MsgC2S.FILE_TRANSFER, 0])))

    def test_a_qemu_extended_key_event_is_stepped_over(self) -> None:
        qemu_extended_key_event = pack(
            "!BBHII", MsgC2S.QEMU_CLIENT_MESSAGE, QemuClientMessage.EXTENDED_KEY_EVENT, 1, 0x61, 30
        )
        buffer = bytearray(qemu_extended_key_event + UPDATE_REQUEST)

        self.assertTrue(replay.saw_update_request(buffer))
        self.assertEqual(bytes(buffer), b"")


class TestReplayProtocol(TestCase):
    def test_greeting_goes_out_before_the_client_has_said_anything(self) -> None:
        protocol = start(NONE_38)

        self.assertEqual(written(protocol), VERSION_38)

    def test_client_that_never_replies_gets_nothing_past_the_greeting(self) -> None:
        protocol = start(NONE_38)

        self.assertEqual(written(protocol), VERSION_38)
        protocol.transport.loseConnection.assert_not_called()

    def test_a_38_handshake_follows_the_client_replies(self) -> None:
        protocol = start(NONE_38)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")  # ClientInit, shared=1
        self.assertEqual(written(protocol), NONE_38[: -len(FRAMEBUFFER)])

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(written(protocol), NONE_38)

    def test_a_pre38_handshake_follows_the_client_replies(self) -> None:
        protocol = start(NONE_33)

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), NONE_33)

    def test_framebuffer_waits_for_the_client_to_ask_for_one(self) -> None:
        protocol = start(NONE_33)

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        self.assertEqual(written(protocol), NONE_33[: -len(FRAMEBUFFER)])

        # SetEncodings: real clients send it first, and it requires no reply.
        protocol.dataReceived(pack("!BxH", MsgC2S.SET_ENCODING, 1) + pack("!i", 0))
        self.assertEqual(written(protocol), NONE_33[: -len(FRAMEBUFFER)])

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(written(protocol), NONE_33)

    def test_a_named_server_is_served_through_the_name_before_the_framebuffer(self) -> None:
        """The grammar ends after the server name, not the 24 fixed ServerInit
        bytes, so a name-len=0 fixture alone would never catch a pacing
        offset that only shows up once a name is present."""
        protocol = start(NONE_38_NAMED)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")  # ClientInit, shared=1
        self.assertEqual(written(protocol), NONE_38_NAMED[: -len(FRAMEBUFFER)])

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(written(protocol), NONE_38_NAMED)

    def test_an_exhausted_capture_leaves_the_connection_to_the_client(self) -> None:
        """An exhausted capture does not hang up; the client closes when it is done."""
        protocol = start(NONE_33)

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)
        before = written(protocol)
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), before)
        protocol.transport.loseConnection.assert_not_called()

    def test_truncated_capture_sends_what_there_is_and_stops(self) -> None:
        """A corrupted capture must not blow up mid-connection."""
        protocol = start(b"RFB 003.")

        self.assertEqual(written(protocol), b"RFB 003.")
        protocol.dataReceived(VERSION_38)
        self.assertEqual(written(protocol), b"RFB 003.")

    def test_a_capture_truncated_mid_name_sends_what_there_is_and_stops(self) -> None:
        """The grammar watches the server name too, so a capture cut off
        inside it must stop cleanly rather than wait forever for the rest."""
        cut_short = (
            VERSION_38
            + bytes([1, AuthTypes.NONE])
            + pack("!I", 0)
            + SERVER_INIT_640x480[:-4]
            + pack("!I", 4)
            + b"NA"  # only half the 4-byte name arrived
        )
        protocol = start(cut_short)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")  # ClientInit, shared=1

        self.assertEqual(written(protocol), cut_short)
        self.assertTrue(protocol.exhausted)

    def test_a_preserved_auth_capture_is_served_verbatim(self) -> None:
        """--capture-raw-unsafe archives keep the original handshake."""
        challenge = bytes(range(16))
        s2c = (
            VERSION_38
            + bytes([1, AuthTypes.VNC_AUTHENTICATION])
            + challenge
            + pack("!I", 0)
            + SERVER_INIT_640x480
            + FRAMEBUFFER
        )
        protocol = start(s2c)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.VNC_AUTHENTICATION]))

        self.assertIn(challenge, written(protocol))

    def test_an_unfollowable_auth_type_cannot_be_paced_so_the_remainder_is_served_unpaced(self) -> None:
        """A preserved archive whose auth type has no grammar can't be paced past the
        handshake; the remainder still goes out, with a warning, instead of hanging."""
        s2c = VERSION_38 + bytes([1, AuthTypes.TIGHT]) + b"UNPACED-REMAINDER"
        protocol = start(s2c)

        protocol.dataReceived(VERSION_38)
        with self.assertLogs(replay.log, "WARNING"):
            protocol.dataReceived(bytes([AuthTypes.TIGHT]))

        self.assertIn(b"UNPACED-REMAINDER", written(protocol))

    def test_data_received_after_exhaustion_does_not_grow_the_buffer(self) -> None:
        protocol = start(NONE_33)
        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)
        self.assertTrue(protocol.exhausted)

        protocol.dataReceived(pack("!BBHH", MsgC2S.POINTER_EVENT, 0, 0, 0))

        self.assertEqual(protocol.buffer, bytearray())

    def test_a_zero_client_timeout_disables_the_stall_warning(self) -> None:
        protocol = start(NONE_38, client_timeout=0)

        with mock.patch.object(replay.reactor, "callLater") as call_later:
            protocol.expect(10)

        call_later.assert_not_called()

    def test_a_connection_that_never_sent_bytes_does_not_stop_the_reactor(self) -> None:
        """A port-poll readiness probe (connect, close, no bytes) must not kill a
        one-shot server before the real client connects."""
        protocol = start(NONE_38)

        with (
            mock.patch.object(replay.reactor, "running", True),
            mock.patch.object(replay.reactor, "stop") as stop,
        ):
            protocol.connectionLost()

        stop.assert_not_called()

    def test_a_connection_that_sent_bytes_stops_the_reactor(self) -> None:
        protocol = start(NONE_38)
        protocol.dataReceived(VERSION_38)

        with (
            mock.patch.object(replay.reactor, "running", True),
            mock.patch.object(replay.reactor, "stop") as stop,
        ):
            protocol.connectionLost()

        stop.assert_called_once()


class TestVersionMatch(TestCase):
    def test_a_version_mismatch_between_the_live_client_and_the_capture_closes_the_connection(self) -> None:
        """The archive's shape is fixed to the version the ORIGINAL client negotiated;
        a live client replying with a different version would otherwise desync it."""
        protocol = start(NONE_38, meta={"negotiated_version": [3, 8]})

        with self.assertLogs(replay.log, "ERROR"):
            protocol.dataReceived(VERSION_33)

        protocol.transport.loseConnection.assert_called_once()

    def test_a_version_match_proceeds_as_normal(self) -> None:
        protocol = start(NONE_38, meta={"negotiated_version": [3, 8]})

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), NONE_38)
        protocol.transport.loseConnection.assert_not_called()

    def test_an_archive_without_a_recorded_version_paces_off_the_live_reply(self) -> None:
        protocol = start(NONE_38)

        protocol.dataReceived(VERSION_38)
        protocol.dataReceived(bytes([AuthTypes.NONE]))
        protocol.dataReceived(b"\x01")
        protocol.dataReceived(UPDATE_REQUEST)

        self.assertEqual(written(protocol), NONE_38)
        protocol.transport.loseConnection.assert_not_called()
