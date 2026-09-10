from __future__ import annotations

import unittest

from PIL import Image

from vncdotool.const import Encoding
from vncdotool.cursor import CursorMode

from tests.unit.utils import (
    _pixel,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)

POINTER_POS = rect(150, 120, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")

IMAGE_2X2 = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
MASK_2X2 = bytes([0b11000000, 0b11000000])


def cursor_rect(hotspot_x: int = 0, hotspot_y: int = 0) -> bytes:
    body = b"".join(_pixel(*p) for p in IMAGE_2X2) + MASK_2X2
    return rect(hotspot_x, hotspot_y, 2, 2, Encoding.PSEUDO_CURSOR, body)


class TestPointerPos(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    def test_position_is_recorded(self) -> None:
        handshake(self.cli, 400, 400)

        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.cli.cursor_pos, (150, 120))

    def test_rectangle_consumes_no_payload(self) -> None:
        """A following rectangle in the same update still decodes."""
        handshake(self.cli, 400, 400)
        self.cli.factory.cursor = CursorMode.LOCAL

        self.cli.dataReceived(framebuffer_update([POINTER_POS, cursor_rect(1, 1)]))

        self.assertEqual(self.cli.cursor_pos, (150, 120))
        self.assertEqual(self.cli.cfocus, (1, 1))

    def test_position_is_not_a_screen_change(self) -> None:
        """Nothing was painted, so the rectangle must not satisfy a refresh."""
        handshake(self.cli, 400, 400)

        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.cli.rectanglePos, [])

    def test_a_move_by_the_script_supersedes_the_server(self) -> None:
        handshake(self.cli, 400, 400)
        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.cli.mouseMove(10, 20)

        self.assertIsNone(self.cli.cursor_pos)

    def test_the_shape_is_drawn_where_the_server_says(self) -> None:
        """--localcursor composites at the server's position, not the script's."""
        handshake(self.cli, 400, 400)
        self.cli.factory.cursor = CursorMode.LOCAL
        self.cli.screen = Image.new("RGB", (400, 400))
        self.cli.mouseMove(10, 20)
        self.cli.dataReceived(framebuffer_update([cursor_rect()]))

        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.cli.screen.getpixel((150, 120)), IMAGE_2X2[0])

    def test_a_click_still_goes_where_the_script_put_it(self) -> None:
        handshake(self.cli, 400, 400)
        self.cli.mouseMove(10, 20)

        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual((self.cli.x, self.cli.y), (10, 20))


if __name__ == "__main__":
    unittest.main()
