"""Runnable pins for two known decoder bugs.

Both tests fail today. They pin that these decoders are broken, not what
correct output looks like: bytes hand-derived from RFC 6143 and checked
against our own decoder cannot verify that decoder.
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
    cli.setEncodings = mock.Mock()  # not under test here
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


class TestDecoderBugs(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    GRID_4X4 = [
        (10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120),
        (130, 140, 150), (160, 170, 180), (190, 200, 210), (220, 230, 240),
        (5, 15, 25), (35, 45, 55), (65, 75, 85), (95, 105, 115),
        (125, 135, 145), (155, 165, 175), (185, 195, 205), (215, 225, 235),
    ]

    @unittest.expectedFailure
    def test_copyrect(self) -> None:
        """CopyRect actually copies the source region to the destination.

        RFBClient.copyRectangle() is a no-op stub nothing overrides.
        """
        width = height = 4
        handshake(self.cli, width, height)

        raw_body = b"".join(_pixel(*p) for p in self.GRID_4X4)
        raw_rect = rect(0, 0, width, height, Encoding.RAW, raw_body)
        copy_body = pack("!HH", 0, 0)  # copy from (0, 0)
        copy_rect = rect(2, 2, 2, 2, Encoding.COPY_RECTANGLE, copy_body)
        self.cli.dataReceived(framebuffer_update([raw_rect, copy_rect]))

        # Whole framebuffer, so the source region has to survive the copy too.
        expected = list(self.GRID_4X4)
        for sy in range(2):
            for sx in range(2):
                expected[(2 + sy) * width + (2 + sx)] = self.GRID_4X4[sy * width + sx]
        self.assertIsNotNone(self.cli.screen)
        assert_pixels(self, self.cli.screen, expected)

    @unittest.expectedFailure
    def test_corre(self) -> None:
        """CoRRE decodes a background plus multiple subrects.

        Two subrects, because _handleDecodeCORRERectangles is broken twice:
        with one, its loop bound terminates correctly by accident and
        fixing only the missing f-prefix would look like a fix.
        """
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


if __name__ == "__main__":
    unittest.main()
