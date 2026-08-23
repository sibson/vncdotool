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
        # Only the Raw rect carries content; DesktopSize is not recorded.
        self.assertEqual(self.cli.rectanglePos, [(0, 0, 4, 4)])


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
