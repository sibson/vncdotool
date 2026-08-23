"""CopyRect decode tests: wire bytes in, framebuffer out."""
from __future__ import annotations

import unittest
from struct import pack

from vncdotool.const import Encoding

from tests.unit.decoder_fixtures import (
    _pixel,
    assert_pixels,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


class TestCopyRect(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    GRID_4X4 = [
        (10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120),
        (130, 140, 150), (160, 170, 180), (190, 200, 210), (220, 230, 240),
        (5, 15, 25), (35, 45, 55), (65, 75, 85), (95, 105, 115),
        (125, 135, 145), (155, 165, 175), (185, 195, 205), (215, 225, 235),
    ]

    def test_copyrect_copies_the_source_region_and_leaves_it_intact(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        raw_body = b"".join(_pixel(*p) for p in self.GRID_4X4)
        raw_rect = rect(0, 0, width, height, Encoding.RAW, raw_body)
        copy_body = pack("!HH", 0, 0)
        copy_rect = rect(2, 2, 2, 2, Encoding.COPY_RECTANGLE, copy_body)
        self.cli.dataReceived(framebuffer_update([raw_rect, copy_rect]))

        # Whole framebuffer, so the source region has to survive the copy too.
        expected = list(self.GRID_4X4)
        for sy in range(2):
            for sx in range(2):
                expected[(2 + sy) * width + (2 + sx)] = self.GRID_4X4[sy * width + sx]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)


if __name__ == "__main__":
    unittest.main()
