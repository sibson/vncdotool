from __future__ import annotations

import unittest

from vncdotool.const import Encoding

from tests.unit.utils import (
    _pixel,
    assert_pixels,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


class TestCursor(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    # 2x2 image at hotspot (1, 1). MASK_2X2 is MSB-first, one bit per
    # pixel; 0b11000000 flags both columns of each row valid.
    IMAGE_2X2 = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    MASK_2X2 = bytes([0b11000000, 0b11000000])

    def test_cursor_sets_image_mask_and_hotspot(self) -> None:
        handshake(self.cli, 4, 4)

        body = b"".join(_pixel(*p) for p in self.IMAGE_2X2) + self.MASK_2X2
        cursor_rect = rect(1, 1, 2, 2, Encoding.PSEUDO_CURSOR, body)
        self.cli.dataReceived(framebuffer_update([cursor_rect]))

        self.assertIsNotNone(self.cli.cursor)
        assert_pixels(self, self.cli.cursor, self.IMAGE_2X2)
        self.assertEqual(self.cli.cfocus, (1, 1))
        self.assertEqual(self.cli.rectanglePos, [(1, 1, 2, 2)])


if __name__ == "__main__":
    unittest.main()
