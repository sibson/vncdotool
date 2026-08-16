"""Unit coverage for vncdotool.replay, the `vncdo-replay --server` half.

`client_timeout=None` throughout: the stall warning is the one thing here
that would touch the global reactor.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from struct import pack
from unittest import TestCase, mock

from vncdotool import replay
from vncdotool.const import AuthTypes, MsgC2S

VERSION_33 = b"RFB 003.003\n"
VERSION_38 = b"RFB 003.008\n"
SERVER_INIT_640x480 = (
    b"\x02\x80\x01\xe0"  # width=640, height=480
    b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
    b"\x00\x00\x00\x00"  # name-len=0
)
FRAMEBUFFER = b"THE-RECORDED-FRAMEBUFFER"
UPDATE_REQUEST = pack("!BBHHHH", MsgC2S.FRAMEBUFFER_UPDATE_REQUEST, 0, 0, 0, 640, 480)

# What a stripped capture holds: a none-auth handshake and then the session.
NONE_38 = VERSION_38 + bytes([1, AuthTypes.NONE]) + pack("!I", 0) + SERVER_INIT_640x480 + FRAMEBUFFER
NONE_33 = VERSION_33 + pack("!I", AuthTypes.NONE) + SERVER_INIT_640x480 + FRAMEBUFFER


def written(protocol) -> bytes:
    """Everything the protocol has sent, in order."""
    return b"".join(call.args[0] for call in protocol.transport.write.call_args_list)


def start(s2c: bytes, **kwargs) -> replay.ReplayProtocol:
    """Build a protocol on a mocked transport and open the connection."""
    factory = replay.ReplayFactory(
        capture=replay.Capture(s2c=s2c, session_vdo=b"", meta=None),
        client_timeout=None,
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
    """Stepping over client messages to find the one that asks for a framebuffer."""

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


class TestReplayProtocol(TestCase):
    """The handshake goes out a step at a time, against the client's replies."""

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
        """A capture holds one finite recording of the framebuffer, so sending
        it before the client asked means the client that asks a moment later
        waits for an update that already went past it."""
        protocol = start(NONE_33)

        protocol.dataReceived(VERSION_33)
        protocol.dataReceived(b"\x01")
        self.assertEqual(written(protocol), NONE_33[: -len(FRAMEBUFFER)])

        # SetEncodings, which a client sends first and which owes it nothing.
        protocol.dataReceived(pack("!BxH", MsgC2S.SET_ENCODING, 1) + pack("!i", 0))
        self.assertEqual(written(protocol), NONE_33[: -len(FRAMEBUFFER)])

        protocol.dataReceived(UPDATE_REQUEST)
        self.assertEqual(written(protocol), NONE_33)

    def test_an_exhausted_capture_leaves_the_connection_to_the_client(self) -> None:
        """Hanging up here would cut short whatever the client is still doing
        with the bytes it has; the original server only closed because its
        own client did."""
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


class TestServerInitEnd(TestCase):
    def test_a_named_server_pushes_the_boundary_out(self) -> None:
        named = SERVER_INIT_640x480[:-4] + pack("!I", 4) + b"NAME"

        self.assertEqual(replay.server_init_end(named, 0), 28)

    def test_a_capture_cut_short_of_the_name_has_no_boundary(self) -> None:
        named = SERVER_INIT_640x480[:-4] + pack("!I", 4) + b"NA"

        self.assertIsNone(replay.server_init_end(named, 0))

    def test_a_capture_cut_short_of_server_init_has_no_boundary(self) -> None:
        self.assertIsNone(replay.server_init_end(SERVER_INIT_640x480[:10], 0))
