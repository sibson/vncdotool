from __future__ import annotations

import unittest

from vncdotool.const import Encoding

from tests.unit.utils import (
    _pixel,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


class TestDesktopSize(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    def test_desktop_size_resizes_screen_and_is_not_a_content_rect(self) -> None:
        handshake(self.cli, 4, 4)

        raw_body = b"".join(_pixel(1, 2, 3) for _ in range(16))
        raw_rect = rect(0, 0, 4, 4, Encoding.RAW, raw_body)
        resize_rect = rect(0, 0, 8, 6, Encoding.PSEUDO_DESKTOP_SIZE)
        self.cli.dataReceived(framebuffer_update([raw_rect, resize_rect]))

        self.assertIsNotNone(self.cli.screen)
        self.assertEqual(self.cli.screen.size, (8, 6))
        self.assertEqual(self.cli.rectanglePos, [(0, 0, 4, 4)])


class TestExtendedDesktopSize(unittest.TestCase):
    """The rectangle bodies here are the bytes TigerVNC 1.12 sent on a raw
    socket, not bytes read back off this decoder.
    """

    # reason 1 (this client), result 0 (success), one 320x240 screen.
    GRANTED = (
        b"\x00\x01\x00\x00\x01\x40\x00\xf0\xff\xff\xfe\xcc"
        b"\x01\x00\x00\x00"
        b"\x6b\x8b\x45\x67\x00\x00\x00\x00\x01\x40\x00\xf0\x00\x00\x00\x00"
    )
    # reason 1, result 3 (invalid layout); the framebuffer stayed 256x192.
    REFUSED = (
        b"\x00\x01\x00\x03\x01\x00\x00\xc0\xff\xff\xfe\xcc"
        b"\x01\x00\x00\x00"
        b"\x6b\x8b\x45\x67\x00\x00\x00\x00\x01\x00\x00\xc0\x00\x00\x00\x00"
    )
    # reason 0, what a non-incremental request draws out of a fresh session.
    ADVERTISED = (
        b"\x00\x00\x00\x00\x01\x00\x00\xc0\xff\xff\xfe\xcc"
        b"\x01\x00\x00\x00"
        b"\x6b\x8b\x45\x67\x00\x00\x00\x00\x01\x00\x00\xc0\x00\x00\x00\x00"
    )

    def setUp(self) -> None:
        self.cli = make_client()
        handshake(self.cli, 256, 192)

    def test_advertisement_records_the_layout_and_is_not_a_content_rect(self) -> None:
        self.cli.dataReceived(framebuffer_update([self.ADVERTISED]))

        self.assertEqual(self.cli.screens, ((0x6B8B4567, 0, 0, 256, 192, 0),))
        self.assertEqual((self.cli.width, self.cli.height), (256, 192))
        self.assertEqual(self.cli.rectanglePos, [])
        self.assertIn(
            Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE, self.cli.negotiated_encodings
        )

    def test_granted_resize_moves_the_framebuffer(self) -> None:
        self.cli.dataReceived(framebuffer_update([self.GRANTED]))

        self.assertEqual((self.cli.width, self.cli.height), (320, 240))
        assert self.cli.screen is not None
        self.assertEqual(self.cli.screen.size, (320, 240))

    def test_refused_resize_leaves_the_framebuffer_alone(self) -> None:
        self.cli.dataReceived(framebuffer_update([self.REFUSED]))

        self.assertEqual((self.cli.width, self.cli.height), (256, 192))

    def test_a_following_rectangle_still_decodes(self) -> None:
        """The screen array's length is what tells the pump where the next
        rectangle starts.
        """
        raw_body = b"".join(_pixel(1, 2, 3) for _ in range(4))
        raw_rect = rect(0, 0, 2, 2, Encoding.RAW, raw_body)
        self.cli.dataReceived(framebuffer_update([self.GRANTED, raw_rect]))

        self.assertEqual(self.cli.rectanglePos, [(0, 0, 2, 2)])

    def test_no_screens_is_decoded(self) -> None:
        empty = b"\x00\x00\x00\x00\x03\x20\x02\x58\xff\xff\xfe\xcc\x00\x00\x00\x00"
        self.cli.dataReceived(framebuffer_update([empty]))

        self.assertEqual(self.cli.screens, ())
        self.assertEqual((self.cli.width, self.cli.height), (800, 600))


class TestQemuExtendedKey(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    def test_qemu_extended_key_is_negotiated_and_is_not_a_content_rect(self) -> None:
        handshake(self.cli, 2, 2)
        self.assertNotIn(
            Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT, self.cli.negotiated_encodings
        )

        qemu_rect = rect(0, 0, 0, 0, Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
        self.cli.dataReceived(framebuffer_update([qemu_rect]))

        self.assertIn(
            Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT, self.cli.negotiated_encodings
        )
        self.assertEqual(self.cli.rectanglePos, [])


if __name__ == "__main__":
    unittest.main()
