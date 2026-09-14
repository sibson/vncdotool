from __future__ import annotations

import io
import unittest
from unittest import mock

from PIL import Image, ImageChops

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
MOVED_POINTER_POS = rect(10, 20, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")
BLACK_PIXEL_AT_ORIGIN = rect(0, 0, 1, 1, Encoding.RAW, _pixel(0, 0, 0))

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

        self.assertEqual((self.cli.x, self.cli.y), (150, 120))

    def test_rectangle_consumes_no_payload(self) -> None:
        """A following rectangle in the same update still decodes."""
        handshake(self.cli, 400, 400)
        self.cli.factory.cursor = CursorMode.LOCAL

        self.cli.dataReceived(framebuffer_update([POINTER_POS, cursor_rect(1, 1)]))

        self.assertEqual((self.cli.x, self.cli.y), (150, 120))
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

        self.assertEqual((self.cli.x, self.cli.y), (10, 20))

    def test_the_shape_is_drawn_where_the_server_says(self) -> None:
        """--localcursor composites at the server's position, not the script's."""
        handshake(self.cli, 400, 400)
        self.cli.factory.cursor = CursorMode.LOCAL
        self.cli.screen = Image.new("RGB", (400, 400))
        self.cli.mouseMove(10, 20)
        self.cli.dataReceived(framebuffer_update([cursor_rect()]))

        self.cli.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.cli._render().getpixel((150, 120)), IMAGE_2X2[0])
        self.assertNotEqual(self.cli.screen.getpixel((150, 120)), IMAGE_2X2[0])

    def test_the_shape_is_absent_without_localcursor(self) -> None:
        handshake(self.cli, 400, 400)
        self.cli.screen = Image.new("RGB", (400, 400))
        self.cli.dataReceived(framebuffer_update([cursor_rect(), POINTER_POS]))

        self.assertIsNone(
            ImageChops.difference(
                self.cli._render(), Image.new("RGB", (400, 400))
            ).getbbox()
        )

    def test_an_incremental_capture_holds_one_cursor(self) -> None:
        """A move leaves nothing behind for a later capture to pick up."""
        handshake(self.cli, 400, 400)
        self.cli.factory.cursor = CursorMode.LOCAL
        self.cli.screen = Image.new("RGB", (400, 400))
        self.cli.dataReceived(framebuffer_update([cursor_rect(), POINTER_POS]))

        fp = io.BytesIO()
        self.cli.captureScreen(fp, incremental=True, format="PNG")
        # One update moving the pointer and repainting a rectangle that does
        # not cover where it was.
        self.cli.dataReceived(
            framebuffer_update([MOVED_POINTER_POS, BLACK_PIXEL_AT_ORIGIN])
        )

        expected = Image.new("RGB", (400, 400))
        for i, pixel in enumerate(IMAGE_2X2):
            expected.putpixel((10 + i % 2, 20 + i // 2), pixel)
        with Image.open(fp) as capture:
            difference = ImageChops.difference(capture.convert("RGB"), expected)
        self.assertIsNone(difference.getbbox(), "capture holds a stale cursor")

    def test_a_click_goes_where_the_pointer_is(self) -> None:
        """A pointer the desktop moved takes the next click with it, as a
        real mouse does; clicking where the script last aimed would put it
        somewhere the pointer is not.
        """
        handshake(self.cli, 400, 400)
        self.cli.mouseMove(10, 20)
        self.cli.dataReceived(framebuffer_update([POINTER_POS]))
        self.cli.pointerEvent = mock.Mock()

        self.cli.mouseDown(1)

        self.cli.pointerEvent.assert_called_once_with(150, 120, buttonmask=1)


if __name__ == "__main__":
    unittest.main()
