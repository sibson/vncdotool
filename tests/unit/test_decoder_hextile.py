from __future__ import annotations

import unittest
from struct import pack
from unittest import mock

from vncdotool.const import Encoding, HextileEncoding

from tests.unit.decoder_fixtures import (
    _pixel,
    assert_pixels,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


def hextile_subrect(x: int, y: int, w: int, h: int) -> bytes:
    """A non-coloured Hextile subrect: x/y packed into one byte, w-1/h-1 into another."""
    return bytes(((x << 4) | y, ((w - 1) << 4) | (h - 1)))


def hextile_tile(
    subencoding: HextileEncoding,
    background: bytes = b"",
    foreground: bytes = b"",
    count: int = 0,
    subrects: bytes = b"",
    raw: bytes = b"",
) -> bytes:
    """One Hextile tile: subencoding byte + whatever fields it flags."""
    if subencoding & HextileEncoding.RAW:
        return pack("!B", int(subencoding)) + raw
    body = background + foreground
    if subencoding & HextileEncoding.ANY_SUBRECTS:
        body += pack("!B", count) + subrects
    return pack("!B", int(subencoding)) + body


def hextile_rect(x: int, y: int, w: int, h: int, tiles: list[bytes]) -> bytes:
    """A Hextile-encoded rectangle: tiles concatenated with no padding between them."""
    return rect(x, y, w, h, Encoding.HEXTILE, b"".join(tiles))


class TestHextile(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    GRID_4X4 = [
        (10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120),
        (130, 140, 150), (160, 170, 180), (190, 200, 210), (220, 230, 240),
        (5, 15, 25), (35, 45, 55), (65, 75, 85), (95, 105, 115),
        (125, 135, 145), (155, 165, 175), (185, 195, 205), (215, 225, 235),
    ]

    def test_hextile_raw_tile_is_pixels_in_row_order(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        raw_body = b"".join(_pixel(*p) for p in self.GRID_4X4)
        tile = hextile_tile(HextileEncoding.RAW, raw=raw_body)
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, self.GRID_4X4)

    def test_hextile_background_only_tile_fills_the_tile(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (1, 2, 3)
        tile = hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*bg))
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        expected = [bg] * (width * height)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_uncoloured_subrects_use_the_tile_foreground(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        subencoding = (
            HextileEncoding.BACKGROUND_SPECIFIED
            | HextileEncoding.FOREGROUND_SPECIFIED
            | HextileEncoding.ANY_SUBRECTS
        )
        tile = hextile_tile(
            subencoding,
            background=_pixel(*bg),
            foreground=_pixel(*fg),
            count=1,
            subrects=hextile_subrect(1, 2, 3, 2),
        )
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        expected = [
            fg if (1 <= x < 4 and 2 <= y < 4) else bg
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_coloured_subrects_carry_their_own_pixel(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        fg1 = (255, 0, 0)
        fg2 = (0, 255, 0)
        subencoding = (
            HextileEncoding.BACKGROUND_SPECIFIED
            | HextileEncoding.ANY_SUBRECTS
            | HextileEncoding.SUBRECTS_COLORED
        )
        subrects = (
            _pixel(*fg1) + hextile_subrect(0, 0, 2, 2)
            + _pixel(*fg2) + hextile_subrect(5, 5, 1, 1)
        )
        tile = hextile_tile(
            subencoding,
            background=_pixel(*bg),
            count=2,
            subrects=subrects,
        )
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        expected = [
            fg1 if (x < 2 and y < 2) else (fg2 if (x, y) == (5, 5) else bg)
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_tile_with_no_colours_specified_reuses_the_previous_tile(self) -> None:
        # Two 16x16 tiles side by side. The second sets neither background
        # nor foreground, so it has to fall back to the first tile's colours.
        width, height = 32, 16
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        full_subencoding = (
            HextileEncoding.BACKGROUND_SPECIFIED
            | HextileEncoding.FOREGROUND_SPECIFIED
            | HextileEncoding.ANY_SUBRECTS
        )
        first_tile = hextile_tile(
            full_subencoding,
            background=_pixel(*bg),
            foreground=_pixel(*fg),
            count=1,
            subrects=hextile_subrect(0, 0, 2, 2),
        )
        second_tile = hextile_tile(
            HextileEncoding.ANY_SUBRECTS,
            count=1,
            subrects=hextile_subrect(3, 3, 1, 1),
        )
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [first_tile, second_tile])])
        )

        expected = [bg] * (width * height)
        for y in range(height):
            for x in range(width):
                if x < 2 and y < 2:
                    expected[y * width + x] = fg
                if x == 16 + 3 and y == 3:
                    expected[y * width + x] = fg
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_walks_tiles_row_by_row(self) -> None:
        """Three tiles across and two down: a two-by-two grid cannot tell a
        row-major walk from a column-major one, since both visit the same
        four positions in the same order.
        """
        width, height = 48, 32
        handshake(self.cli, width, height)

        colours = [(10, 0, 0), (0, 20, 0), (0, 0, 30), (40, 40, 0), (0, 50, 50), (60, 0, 60)]
        tiles = [
            hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*colour))
            for colour in colours
        ]
        self.cli.dataReceived(framebuffer_update([hextile_rect(0, 0, width, height, tiles)]))

        expected = [
            colours[(y // 16) * 3 + (x // 16)]
            for y in range(height)
            for x in range(width)
        ]
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_colours_do_not_carry_across_a_raw_tile(self) -> None:
        """rfbproto: a background may not be carried over if the previous tile
        was raw. So the third tile here has no colour to paint with.
        """
        width, height = 48, 16
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        raw_pixels = b"".join(_pixel(1, 2, 3) for _ in range(16 * 16))
        tiles = [
            hextile_tile(
                HextileEncoding.BACKGROUND_SPECIFIED | HextileEncoding.FOREGROUND_SPECIFIED,
                background=_pixel(0, 0, 90), foreground=_pixel(200, 0, 0),
            ),
            hextile_tile(HextileEncoding.RAW) + raw_pixels,
            hextile_tile(HextileEncoding(0)),
        ]
        self.cli.dataReceived(framebuffer_update([hextile_rect(0, 0, width, height, tiles)]))

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()

    def test_hextile_a_tile_declaring_no_subrects_needs_no_foreground(self) -> None:
        """AnySubrects with a count of zero is redundant but well-formed, and
        an encoder that always sets the bit emits it.
        """
        width = height = 16
        handshake(self.cli, width, height)

        background = (255, 0, 0)
        tiles = [
            hextile_tile(
                HextileEncoding.BACKGROUND_SPECIFIED | HextileEncoding.ANY_SUBRECTS,
                background=_pixel(*background), count=0,
            )
        ]
        self.cli.dataReceived(framebuffer_update([hextile_rect(0, 0, width, height, tiles)]))

        assert_pixels(self, self.cli.screen, [background] * (width * height))

    def test_hextile_rectangle_not_a_multiple_of_16_has_partial_edge_tiles(self) -> None:
        # 20x20: tiles are 16x16, 4x16, 16x4, 4x4 -- a decoder that assumes
        # square 16x16 tiles will misplace or crash on the last row/column.
        width = height = 20
        handshake(self.cli, width, height)

        top_left = (10, 20, 30)
        top_right = (40, 50, 60)
        bottom_left = (70, 80, 90)
        bottom_right = (100, 110, 120)
        tiles = [
            hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*top_left)),
            hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*top_right)),
            hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*bottom_left)),
            hextile_tile(HextileEncoding.BACKGROUND_SPECIFIED, background=_pixel(*bottom_right)),
        ]
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, tiles)])
        )

        expected = []
        for y in range(height):
            for x in range(width):
                if x < 16 and y < 16:
                    expected.append(top_left)
                elif x >= 16 and y < 16:
                    expected.append(top_right)
                elif x < 16 and y >= 16:
                    expected.append(bottom_left)
                else:
                    expected.append(bottom_right)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_rectangle_position_is_screen_relative_but_tiles_are_rectangle_local(self) -> None:
        screen_width = screen_height = 8
        handshake(self.cli, screen_width, screen_height)

        base = (0, 0, 0)
        bg = (0, 0, 255)
        fg = (255, 0, 0)
        base_body = b"".join(_pixel(*base) for _ in range(screen_width * screen_height))
        base_rect = rect(0, 0, screen_width, screen_height, Encoding.RAW, base_body)

        subencoding = (
            HextileEncoding.BACKGROUND_SPECIFIED
            | HextileEncoding.FOREGROUND_SPECIFIED
            | HextileEncoding.ANY_SUBRECTS
        )
        tile = hextile_tile(
            subencoding,
            background=_pixel(*bg),
            foreground=_pixel(*fg),
            count=1,
            subrects=hextile_subrect(1, 0, 1, 1),
        )
        hex_rect = hextile_rect(2, 2, 2, 2, [tile])

        self.cli.dataReceived(framebuffer_update([base_rect, hex_rect]))

        expected = [base] * (screen_width * screen_height)
        for y in range(2):
            for x in range(2):
                expected[(2 + y) * screen_width + (2 + x)] = bg
        expected[2 * screen_width + 3] = fg  # rect-local (1, 0) -> screen (3, 2)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_hextile_subrect_past_tile_edge_is_a_protocol_error(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        subencoding = (
            HextileEncoding.BACKGROUND_SPECIFIED
            | HextileEncoding.FOREGROUND_SPECIFIED
            | HextileEncoding.ANY_SUBRECTS
        )
        # tile is 8x8 (rectangle smaller than one full tile); x+w = 7+2 = 9 > 8
        tile = hextile_tile(
            subencoding,
            background=_pixel(*bg),
            foreground=_pixel(*fg),
            count=1,
            subrects=hextile_subrect(7, 0, 2, 1),
        )
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()

    def test_hextile_first_tile_without_background_is_a_protocol_error(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        # No BACKGROUND_SPECIFIED bit anywhere, and no earlier tile to
        # inherit one from.
        tile = hextile_tile(HextileEncoding(0))
        self.cli.dataReceived(
            framebuffer_update([hextile_rect(0, 0, width, height, [tile])])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
