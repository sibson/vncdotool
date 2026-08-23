from __future__ import annotations

import unittest
from struct import pack
from unittest import mock

from vncdotool.const import Encoding

from tests.unit.decoder_fixtures import (
    _pixel,
    assert_pixels,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


class TestRRE(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    def test_rre_zero_subrects_fills_the_rectangle_with_the_background(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (1, 2, 3)
        body = pack("!I", 0) + _pixel(*bg)
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.RRE, body)])
        )

        expected = [bg] * (width * height)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_rre_decodes_a_background_and_several_subrects(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        fg = (255, 0, 0)  # off-origin, interior
        fg2 = (0, 255, 0)  # touches the right and bottom edge
        subrects = (
            pack("!4sHHHH", _pixel(*fg), 1, 1, 1, 1)
            + pack("!4sHHHH", _pixel(*fg2), 3, 3, 1, 1)
        )
        body = pack("!I", 2) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.RRE, body)])
        )

        expected = [
            fg2 if (x, y) == (3, 3) else (fg if (x, y) == (1, 1) else bg)
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_rre_subrect_coordinates_are_rectangle_local(self) -> None:
        # A 2x2 RRE rectangle placed at (2, 2) of a 4x4 screen. Its
        # subrectangle sits at rect-local (1, 0), i.e. screen (3, 2) -- a
        # decoder that read subrect coordinates as screen-absolute would
        # instead paint (1, 0) or crash on an out-of-bounds fill.
        screen_width = screen_height = 4
        handshake(self.cli, screen_width, screen_height)

        base = (0, 0, 0)
        bg = (0, 0, 255)
        fg = (255, 0, 0)
        base_body = b"".join(_pixel(*base) for _ in range(screen_width * screen_height))
        base_rect = rect(0, 0, screen_width, screen_height, Encoding.RAW, base_body)

        subrects = pack("!4sHHHH", _pixel(*fg), 1, 0, 1, 1)
        rre_body = pack("!I", 1) + _pixel(*bg) + subrects
        rre_rect = rect(2, 2, 2, 2, Encoding.RRE, rre_body)

        self.cli.dataReceived(framebuffer_update([base_rect, rre_rect]))

        expected = [base] * (screen_width * screen_height)
        for y in range(2):
            for x in range(2):
                expected[(2 + y) * screen_width + (2 + x)] = bg
        expected[2 * screen_width + 3] = fg  # rect-local (1, 0) -> screen (3, 2)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_rre_overlapping_subrects_paint_in_wire_order(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        first = (255, 0, 0)
        second = (0, 255, 0)  # overlaps `first`, drawn after it
        subrects = (
            pack("!4sHHHH", _pixel(*first), 0, 0, 3, 3)
            + pack("!4sHHHH", _pixel(*second), 1, 1, 3, 3)
        )
        body = pack("!I", 2) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.RRE, body)])
        )

        expected = [
            second if (1 <= x < 4 and 1 <= y < 4) else (first if (x < 3 and y < 3) else bg)
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_rre_subrect_past_rectangle_edge_is_a_protocol_error(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        subrects = pack("!4sHHHH", _pixel(*fg), 3, 3, 2, 2)  # x+w = 5 > width
        body = pack("!I", 1) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.RRE, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()

    def test_rre_subrect_count_larger_than_rectangle_pixels_is_a_protocol_error(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        bg = (0, 0, 255)
        body = pack("!I", width * height + 1) + _pixel(*bg)
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.RRE, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()


class TestCoRRE(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    def test_corre_zero_subrects_fills_the_rectangle_with_the_background(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (1, 2, 3)
        body = pack("!I", 0) + _pixel(*bg)
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.CORRE, body)])
        )

        expected = [bg] * (width * height)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_corre_decodes_a_background_and_several_subrects(self) -> None:
        # Two subrects: with one, a decoder that reads only the first still
        # produces the right picture.
        width = height = 4
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        fg2 = (0, 255, 0)
        # CoRRE subrects are (4 + bypp) bytes: color, then x, y, w, h as u8.
        subrects = pack("!4sBBBB", _pixel(*fg), 1, 1, 2, 2) + pack("!4sBBBB", _pixel(*fg2), 0, 3, 4, 1)
        body = pack("!I", 2) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.CORRE, body)])
        )

        expected = [
            fg2 if y == 3 else (fg if (1 <= x < 3 and 1 <= y < 3) else bg)
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_corre_subrect_coordinates_are_rectangle_local(self) -> None:
        screen_width = screen_height = 4
        handshake(self.cli, screen_width, screen_height)

        base = (0, 0, 0)
        bg = (0, 0, 255)
        fg = (255, 0, 0)
        base_body = b"".join(_pixel(*base) for _ in range(screen_width * screen_height))
        base_rect = rect(0, 0, screen_width, screen_height, Encoding.RAW, base_body)

        subrects = pack("!4sBBBB", _pixel(*fg), 1, 0, 1, 1)
        corre_body = pack("!I", 1) + _pixel(*bg) + subrects
        corre_rect = rect(2, 2, 2, 2, Encoding.CORRE, corre_body)

        self.cli.dataReceived(framebuffer_update([base_rect, corre_rect]))

        expected = [base] * (screen_width * screen_height)
        for y in range(2):
            for x in range(2):
                expected[(2 + y) * screen_width + (2 + x)] = bg
        expected[2 * screen_width + 3] = fg  # rect-local (1, 0) -> screen (3, 2)
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_corre_overlapping_subrects_paint_in_wire_order(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        bg = (0, 0, 255)
        first = (255, 0, 0)
        second = (0, 255, 0)  # overlaps `first`, drawn after it
        subrects = (
            pack("!4sBBBB", _pixel(*first), 0, 0, 3, 3)
            + pack("!4sBBBB", _pixel(*second), 1, 1, 3, 3)
        )
        body = pack("!I", 2) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.CORRE, body)])
        )

        expected = [
            second if (1 <= x < 4 and 1 <= y < 4) else (first if (x < 3 and y < 3) else bg)
            for y in range(height)
            for x in range(width)
        ]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    def test_corre_subrect_past_rectangle_edge_is_a_protocol_error(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        bg = (0, 0, 255)
        fg = (255, 0, 0)
        subrects = pack("!4sBBBB", _pixel(*fg), 3, 3, 2, 2)  # x+w = 5 > width
        body = pack("!I", 1) + _pixel(*bg) + subrects
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.CORRE, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()

    def test_corre_subrect_count_larger_than_rectangle_pixels_is_a_protocol_error(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        bg = (0, 0, 255)
        body = pack("!I", width * height + 1) + _pixel(*bg)
        self.cli.dataReceived(
            framebuffer_update([rect(0, 0, width, height, Encoding.CORRE, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
