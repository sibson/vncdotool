"""Unit coverage for vnclog's proxy halves.

Both protocol classes are driven directly on mocked transports through a
scripted handshake, so the observer client runs for real without a reactor.
"""

from __future__ import annotations

import dataclasses
import logging
import unittest
from struct import pack
from unittest import TestCase, mock

from vncdotool import pixelformat
from vncdotool.const import AuthTypes, Encoding, MsgC2S, MsgS2C, QemuClientMessage
from vncdotool.loggingproxy import (
    TYPE_LEN,
    VNCLoggingClientProxy,
    VNCLoggingServerFactory,
    VNCLoggingServerProxy,
)

VERSION_38 = b"RFB 003.008\n"
NATIVE = pixelformat.PIXEL_FORMATS["bgrx8888"]
RGB565 = pixelformat.PIXEL_FORMATS["rgb565"]

RED_565 = b"\x00\xf8"
BLUE_565 = b"\x1f\x00"


def raw_update(x: int, y: int, w: int, h: int, pixels: bytes) -> bytes:
    return (
        pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, 1)
        + pack("!HHHHi", x, y, w, h, Encoding.RAW)
        + pixels
    )


class ProxyPair(TestCase):
    def setUp(self) -> None:
        self.factory = VNCLoggingServerFactory("localhost", 5900)
        self.factory.password_required = False

        self.server_proxy = VNCLoggingServerProxy()
        self.server_proxy.transport = mock.Mock()
        self.server_proxy.factory = self.factory
        self.client_proxy = VNCLoggingClientProxy()
        self.client_proxy.transport = mock.Mock()
        self.server_proxy.peer = self.client_proxy
        self.client_proxy.peer = self.server_proxy

        self.server_proxy.connectionMade()
        self.server_proxy.recorder = mock.Mock()

        self.client_proxy.dataReceived(VERSION_38)
        self.server_proxy.dataReceived(VERSION_38)
        self.client_proxy.dataReceived(bytes([1, AuthTypes.NONE]))
        self.server_proxy.dataReceived(bytes([AuthTypes.NONE]))
        self.client_proxy.dataReceived(b"\x00\x00\x00\x00")
        self.server_proxy.dataReceived(b"\x01")  # ClientInit: starts the observer
        self.client_proxy.dataReceived(
            pack("!HH16sI", 2, 1, NATIVE.to_bytes(), 4) + b"test"
        )

        self.observer = self.client_proxy.vnclog
        assert self.observer is not None

    def setPixelFormat(self, pixel_format: pixelformat.PixelFormat) -> None:
        self.server_proxy.dataReceived(
            pack("!Bxxx16s", MsgC2S.SET_PIXEL_FORMAT, pixel_format.to_bytes())
        )


class TestObserverPixelFormat(ProxyPair):

    def test_observer_starts_at_the_format_serverinit_announced(self) -> None:
        self.assertEqual(self.observer.pixel_format, NATIVE)

    def test_observer_adopts_a_format_the_client_asks_for(self) -> None:
        self.setPixelFormat(RGB565)

        self.assertEqual(self.observer.pixel_format, RGB565)
        self.assertEqual(self.observer._image_mode, pixelformat.raw_mode(RGB565))

    def test_observer_decodes_the_stream_at_the_new_format(self) -> None:
        """Two updates, so the second only parses if the first consumed the
        right number of bytes: at the native 4 bytes per pixel the observer
        eats into the next message and desynchronises for good.
        """
        self.setPixelFormat(RGB565)

        self.client_proxy.dataReceived(raw_update(0, 0, 2, 1, RED_565 + BLUE_565))
        self.client_proxy.dataReceived(raw_update(0, 0, 2, 1, BLUE_565 + RED_565))

        self.assertFalse(self.observer._aborted)
        assert self.observer.screen is not None
        self.assertEqual(
            [self.observer.screen.getpixel((0, 0)), self.observer.screen.getpixel((1, 0))],
            [(0, 0, 255), (255, 0, 0)],
        )

    def test_a_format_the_observer_cannot_unpack_fails_it_cleanly(self) -> None:
        """The real client is free to ask for something vncdotool cannot
        decode; that must not raise out of the proxy's parser.
        """
        with self.assertLogs("vncdotool.loggingproxy", level=logging.ERROR):
            self.setPixelFormat(dataclasses.replace(RGB565, truecolor=False))

        self.assertTrue(self.observer._aborted)


class TestObserverEncodingsOffered(ProxyPair):

    def setEncodings(self, *encodings: int) -> None:
        self.server_proxy.dataReceived(
            pack("!BxH", MsgC2S.SET_ENCODING, len(encodings))
            + b"".join(pack("!i", e) for e in encodings)
        )

    def setUp(self) -> None:
        super().setUp()
        self.observer.encodingsOffered = mock.Mock()

    def test_a_pseudo_encoding_reaches_the_observer(self) -> None:
        """Encoding types are signed on the wire and every pseudo-encoding is
        negative, so reading them unsigned puts SetEncodings past the end of
        the enum and takes the proxy down with it.
        """
        self.setEncodings(Encoding.TIGHT, Encoding.PSEUDO_CURSOR)

        self.observer.encodingsOffered.assert_called_once_with(
            frozenset({Encoding.TIGHT, Encoding.PSEUDO_CURSOR})
        )

    def test_an_encoding_with_no_name_is_dropped_not_raised(self) -> None:
        """A client may offer a vendor encoding this enum has never heard of."""
        self.setEncodings(Encoding.RAW, 0x12345678)

        self.observer.encodingsOffered.assert_called_once_with(
            frozenset({Encoding.RAW})
        )


class TestObserverFailureIsReported(ProxyPair):

    def test_an_unreadable_server_message_is_reported_not_raised(self) -> None:
        """VNCDoToolClient reports a protocol error to its factory, and the
        observer's factory is the proxy's own.
        """
        unknown_message = bytes([250])

        with self.assertLogs("vncdotool.loggingproxy", level=logging.ERROR) as logged:
            self.client_proxy.dataReceived(unknown_message)

        self.assertIn("unknown message received", "\n".join(logged.output))
        self.assertTrue(self.observer._aborted)
        # The byte still reached the real client: only the observer gave up.
        self.server_proxy.transport.write.assert_any_call(unknown_message)


class TestClientCutText(ProxyPair):
    def test_parses_and_delivers_its_text(self) -> None:
        """A missing TYPE_LEN entry used to consume zero bytes and spin
        _handle_protocol forever on this message; this must drain the
        buffer and reach the handler instead.
        """
        self.server_proxy.handle_clientCutText = mock.Mock()
        text = b"hello clipboard"

        self.server_proxy.dataReceived(
            pack("!BxxxI", MsgC2S.CLIENT_CUT_TEXT, len(text)) + text
        )

        self.server_proxy.handle_clientCutText.assert_called_once_with(text)
        self.assertEqual(self.server_proxy.buffer, bytearray())

    def test_text_arriving_after_the_header_is_still_delivered(self) -> None:
        self.server_proxy.handle_clientCutText = mock.Mock()
        text = b"split clipboard"

        self.server_proxy.dataReceived(pack("!BxxxI", MsgC2S.CLIENT_CUT_TEXT, len(text)))
        self.server_proxy.handle_clientCutText.assert_not_called()
        self.server_proxy.dataReceived(text)

        self.server_proxy.handle_clientCutText.assert_called_once_with(text)


class TestQemuClientMessage(ProxyPair):
    def test_extended_key_event_parses_without_raising(self) -> None:
        """QEMU_CLIENT_MESSAGE is 2 bytes (type + subtype); a TYPE_LEN of 1
        starved unpack() of the subtype byte and raised struct.error."""
        self.server_proxy.handle_keyEventExtended = mock.Mock()

        self.server_proxy.dataReceived(
            pack("!BB", MsgC2S.QEMU_CLIENT_MESSAGE, QemuClientMessage.EXTENDED_KEY_EVENT)
            + pack("!HII", 1, 0xFFE1, 42)
        )

        self.server_proxy.handle_keyEventExtended.assert_called_once_with(0xFFE1, 1, 42)


class TestMessageSplitAcrossReads(ProxyPair):
    def test_a_message_split_across_two_reads_is_not_stalled_on_an_extra_byte(self) -> None:
        """_handle_protocol staged nbytes + 1 for a short read, so a message
        that arrived complete still waited for one more, unrelated byte."""
        self.server_proxy.handle_keyEvent = mock.Mock()
        message = pack("!BBxxI", MsgC2S.KEY_EVENT, 1, 65)  # 8 bytes total

        self.server_proxy.dataReceived(message[:7])
        self.server_proxy.handle_keyEvent.assert_not_called()
        self.server_proxy.dataReceived(message[7:])

        self.server_proxy.handle_keyEvent.assert_called_once_with(65, 1)


# Messages the proxy deliberately does not decode: they fall to the `else:
# raise ProtocolError` branch in _handle_protocol and are reported, not
# parsed. Listed explicitly so a real gap in TYPE_LEN (like the two bugs
# above) fails test_every_message_type_is_sized_or_documented below instead
# of silently corrupting the parse of every message that follows it.
UNSUPPORTED_C2S = {
    MsgC2S.FILE_TRANSFER,
    MsgC2S.SET_SCALE,
    MsgC2S.SET_SERVER_INPUT,
    MsgC2S.SET_SW,
    MsgC2S.TEXT_CHAT,
    MsgC2S.KEY_FRAME_REquest,
    MsgC2S.KEEP_ALIVE,
    MsgC2S.ULTRA_14,
    MsgC2S.SET_SCALE_FACTOR,
    MsgC2S.ULTRA_16,
    MsgC2S.ULTRA_17,
    MsgC2S.ULTRA_18,
    MsgC2S.ULTRA_19,
    MsgC2S.REQUEST_SESSION,
    MsgC2S.SET_SESSION,
    MsgC2S.NOTIFY_PLUGIN_STREAMING,
    MsgC2S.VMWARE_127,
    MsgC2S.CAR_CONNECTIVITY,
    MsgC2S.ENABLE_CONTINUOUS_UPDATES,
    MsgC2S.OLIVE_CALL_CONTROL,
    MsgC2S.XVP_CLIENT_MESSAGE,
    MsgC2S.SET_DESKTOP_SIZE,
    MsgC2S.TIGHT,
    MsgC2S.GII_CLIENT_MESSAGE,
    MsgC2S.VMWARE_254,
}


class MsgC2STypeLenCheck:
    member: MsgC2S

    def test_type_len_entry_matches_support_status(self) -> None:
        if self.member in UNSUPPORTED_C2S:
            self.assertNotIn(  # type: ignore[attr-defined]
                self.member, TYPE_LEN,
                f"{self.member!r} is listed as unsupported but also has a "
                "TYPE_LEN entry; drop it from UNSUPPORTED_C2S",
            )
        else:
            self.assertIn(  # type: ignore[attr-defined]
                self.member, TYPE_LEN,
                f"{self.member!r} has no TYPE_LEN entry and is not listed in "
                "UNSUPPORTED_C2S -- give it a length or document why not",
            )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(tests)
    for member in MsgC2S:
        name = f"TestTypeLen_{member.name}"
        case = type(name, (MsgC2STypeLenCheck, unittest.TestCase), {"member": member})
        suite.addTest(case("test_type_len_entry_matches_support_status"))
    return suite
