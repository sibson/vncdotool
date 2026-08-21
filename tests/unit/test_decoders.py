"""Per-encoding decode tests: wire bytes in, framebuffer out.

Bytes are hand-derived from RFC 6143 and rfbproto, apart from the bounds
this implementation chose, which are noted where they are decided. That is
enough to pin a decoder against a picture, and is not enough to call an
encoding verified against a real server -- specs/decoder-goldens.md is
where that happens.
"""
from __future__ import annotations

import unittest
from struct import pack
from unittest import mock

from vncdotool import client, rfb
from vncdotool.const import AuthTypes, Encoding, MsgS2C

# The default PixelFormat() maps to image_mode="RGBX", so every fixture
# below is written in that wire byte order: R, G, B, pad.
PIXEL_FORMAT = rfb.PixelFormat()
BYPP = PIXEL_FORMAT.bypp
if BYPP != 4:  # every fixture below hard-codes 4-byte pixels
    raise RuntimeError(f"default PixelFormat is no longer 32bpp (bypp={BYPP}); rewrite the fixtures")


def _pixel(r: int, g: int, b: int) -> bytes:
    """One RGBX pixel on the wire, in the client's negotiated format."""
    return bytes((r, g, b, 0))


def make_client() -> client.VNCDoToolClient:
    cli = client.VNCDoToolClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    cli.factory.shared = 0
    cli.factory.password = None
    # A bare Mock's attributes are all truthy, so the pseudo-encoding flags
    # need pinning to real booleans.
    cli.factory.nocursor = False
    cli.factory.pseudocursor = False
    cli.factory.pseudodesktop = False
    cli.factory.last_rect = False
    cli.factory.qemu_extended_key = False
    cli.setEncodings = mock.Mock()
    return cli


def handshake(cli: client.VNCDoToolClient, width: int, height: int) -> None:
    """Drive an RFB 3.3 / AuthTypes.NONE handshake + ServerInit through dataReceived."""
    cli.dataReceived(b"RFB 003.003\n")
    cli.dataReceived(pack("!I", AuthTypes.NONE))
    server_init = pack("!HH16sI", width, height, PIXEL_FORMAT.to_bytes(), 0)
    cli.dataReceived(server_init)


def rect(x: int, y: int, w: int, h: int, encoding: Encoding, body: bytes = b"") -> bytes:
    """One FramebufferUpdate rectangle: 12-byte header + encoding-specific body."""
    return pack("!HHHHi", x, y, w, h, int(encoding)) + body


def framebuffer_update(rects: list[bytes]) -> bytes:
    """A full FramebufferUpdate server message, msgid included."""
    header = pack("!BxH", MsgS2C.FRAMEBUFFER_UPDATE, len(rects))
    return header + b"".join(rects)


def assert_pixels(test: unittest.TestCase, image, expected: list[tuple[int, int, int]]) -> None:
    """Compare a decoded PIL image against a flat, row-major RGB pixel list."""
    width, height = image.size
    if width * height != len(expected):
        test.fail(
            f"pixel count mismatch: image is {width}x{height} ({width * height} px), "
            f"expected {len(expected)} px"
        )
    rgb = image.convert("RGB")
    for i, want in enumerate(expected):
        x, y = i % width, i // width
        got = rgb.getpixel((x, y))
        if got != want:
            test.fail(f"pixel mismatch at ({x}, {y}): got {got} want {want}")


class TestEncodings(unittest.TestCase):
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
