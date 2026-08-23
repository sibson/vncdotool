from __future__ import annotations

import unittest
import zlib
from struct import pack
from unittest import mock

from vncdotool import rfb
from vncdotool.const import Encoding

from tests.unit.utils import (
    assert_pixels,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)


def _cpixel(r: int, g: int, b: int) -> bytes:
    """One CPIXEL: 3 bytes, no pad. Matches the default test PixelFormat's
    low placement (redshift=0, greenshift=8, blueshift=16), so the buffer
    a ZRLE tile fills is byte-identical to a Raw tile of the same pixels.
    """
    return bytes((r, g, b))


def zrle_run(pixel: bytes, run_length: int) -> bytes:
    """RLE run: a pixel followed by (run_length - 1) as one byte plus as
    many 255-continuation bytes as needed.
    """
    n = run_length - 1
    out = bytearray()
    while n >= 255:
        out.append(255)
        n -= 255
    out.append(n)
    return pixel + bytes(out)


def zrle_pack_indices(indices: list[int], width: int, bits: int) -> bytes:
    """Palette indices packed MSB-first, ``8 // bits`` per byte, with each
    tile row padded to a whole byte independently of the others (RFC 6143
    7.7.6: "padding bits are used to align each row to an exact number of
    bytes").
    """
    per_byte = 8 // bits
    out = bytearray()
    for row_start in range(0, len(indices), width):
        row = indices[row_start:row_start + width]
        for i in range(0, len(row), per_byte):
            group = row[i:i + per_byte]
            byte = 0
            for j, value in enumerate(group):
                byte |= value << (8 - bits - j * bits)
            out.append(byte)
    return bytes(out)


class ZRLEStream:
    """One zlib compressor standing in for the server's single connection
    stream, so a test can prove the decoder's own stream persists across
    more than one rectangle (RFC 6143 7.7.6).
    """

    def __init__(self) -> None:
        self._compressor = zlib.compressobj(6, zlib.DEFLATED, 15)

    def rect_body(self, tile_bytes: bytes) -> bytes:
        compressed = self._compressor.compress(tile_bytes) + self._compressor.flush(zlib.Z_SYNC_FLUSH)
        return pack("!L", len(compressed)) + compressed


def zrle_rect(x: int, y: int, w: int, h: int, tile_bytes: bytes, stream: ZRLEStream | None = None) -> bytes:
    stream = stream or ZRLEStream()
    return rect(x, y, w, h, Encoding.ZRLE, stream.rect_body(tile_bytes))


class TestZRLE(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = make_client()

    GRID_4X4 = [
        (10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120),
        (130, 140, 150), (160, 170, 180), (190, 200, 210), (220, 230, 240),
        (5, 15, 25), (35, 45, 55), (65, 75, 85), (95, 105, 115),
        (125, 135, 145), (155, 165, 175), (185, 195, 205), (215, 225, 235),
    ]

    def test_zrle_raw_tile_is_pixels_in_row_order(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        raw_body = pack("!B", 0) + b"".join(_cpixel(*p) for p in self.GRID_4X4)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, raw_body)])
        )

        assert_pixels(self, self.cli.screen, self.GRID_4X4)

    def test_zrle_solid_tile_fills_the_tile(self) -> None:
        width = height = 4
        handshake(self.cli, width, height)

        colour = (1, 2, 3)
        body = pack("!B", 1) + _cpixel(*colour)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [colour] * (width * height))

    def test_zrle_packed_palette_2_colours_uses_bit_indices(self) -> None:
        width, height = 8, 1
        handshake(self.cli, width, height)

        palette = [(255, 0, 0), (0, 255, 0)]
        indices = [0, 1, 0, 1, 1, 1, 0, 0]
        body = (
            pack("!B", 2)
            + b"".join(_cpixel(*c) for c in palette)
            + zrle_pack_indices(indices, width, bits=1)
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [palette[i] for i in indices])

    def test_zrle_packed_palette_4_colours_uses_dibit_indices(self) -> None:
        width, height = 8, 1
        handshake(self.cli, width, height)

        palette = [(10, 0, 0), (20, 0, 0), (30, 0, 0), (40, 0, 0)]
        indices = [0, 1, 2, 3, 3, 2, 1, 0]
        body = (
            pack("!B", 4)
            + b"".join(_cpixel(*c) for c in palette)
            + zrle_pack_indices(indices, width, bits=2)
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [palette[i] for i in indices])

    def test_zrle_packed_palette_16_colours_uses_nibble_indices(self) -> None:
        width, height = 16, 1
        handshake(self.cli, width, height)

        palette = [(i, i, i) for i in range(16)]
        indices = list(range(16))
        body = (
            pack("!B", 16)
            + b"".join(_cpixel(*c) for c in palette)
            + zrle_pack_indices(indices, width, bits=4)
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [palette[i] for i in indices])

    def test_zrle_packed_palette_rows_are_individually_byte_padded(self) -> None:
        """RFC 6143 7.7.6: "padding bits are used to align each row to an
        exact number of bytes" -- a tile width that doesn't divide the byte
        evenly (5 pixels at 1 bit each leaves 3 padding bits) must not let
        that padding bleed into the next row's indices.
        """
        width, height = 5, 3
        handshake(self.cli, width, height)

        palette = [(0, 0, 0), (255, 0, 0)]
        indices = [
            1, 0, 0, 1, 0,
            0, 1, 1, 0, 0,
            0, 0, 0, 0, 1,
        ]
        body = (
            pack("!B", 2)
            + b"".join(_cpixel(*c) for c in palette)
            + zrle_pack_indices(indices, width, bits=1)
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [palette[i] for i in indices])

    def test_zrle_plain_rle_run_extends_past_255(self) -> None:
        # A single 64x5 tile (320 pixels) so one RLE run covers the whole
        # tile and needs a 255-continuation byte.
        width, height = 64, 5
        handshake(self.cli, width, height)

        colour = (9, 9, 9)
        body = pack("!B", 0x80) + zrle_run(_cpixel(*colour), width * height)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [colour] * (width * height))

    def test_zrle_palette_rle_mixes_single_and_run_pixels(self) -> None:
        width, height = 6, 1
        handshake(self.cli, width, height)

        palette = [(1, 0, 0), (0, 1, 0)]
        # index 0 once (run length 1, top bit clear), then index 1 for a
        # run of 5 (top bit set, run length - 1 = 4 in the next byte).
        body = (
            pack("!B", 0x80 | 2)
            + b"".join(_cpixel(*c) for c in palette)
            + bytes((0x00,))
            + bytes((0x80 | 1, 4))
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        expected = [palette[0]] + [palette[1]] * 5
        assert_pixels(self, self.cli.screen, expected)

    def test_zrle_tile_walks_row_by_row(self) -> None:
        """Three tiles across, two down: same trap as Hextile's equivalent
        test -- a 2x2 grid can't distinguish row-major from column-major.
        """
        width, height = 192, 128
        handshake(self.cli, width, height)

        colours = [(10, 0, 0), (0, 20, 0), (0, 0, 30), (40, 40, 0), (0, 50, 50), (60, 0, 60)]
        stream = ZRLEStream()
        tiles_body = b"".join(pack("!B", 1) + _cpixel(*c) for c in colours)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, tiles_body, stream)])
        )

        expected = [
            colours[(y // 64) * 3 + (x // 64)]
            for y in range(height)
            for x in range(width)
        ]
        assert_pixels(self, self.cli.screen, expected)

    def test_zrle_rectangle_not_a_multiple_of_64_has_partial_edge_tiles(self) -> None:
        width = height = 80
        handshake(self.cli, width, height)

        top_left, top_right = (10, 20, 30), (40, 50, 60)
        bottom_left, bottom_right = (70, 80, 90), (100, 110, 120)
        body = b"".join(
            pack("!B", 1) + _cpixel(*c)
            for c in (top_left, top_right, bottom_left, bottom_right)
        )
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        expected = []
        for y in range(height):
            for x in range(width):
                if x < 64 and y < 64:
                    expected.append(top_left)
                elif x >= 64 and y < 64:
                    expected.append(top_right)
                elif x < 64 and y >= 64:
                    expected.append(bottom_left)
                else:
                    expected.append(bottom_right)
        assert_pixels(self, self.cli.screen, expected)

    def test_zrle_stream_persists_across_rectangles(self) -> None:
        """The decoder keeps one zlib stream for the connection: a second
        rectangle compressed as a continuation of the first, not fresh,
        must still decode -- proving the decoder isn't resetting its
        stream per rectangle (RFC 6143 7.7.6).
        """
        width = height = 2
        handshake(self.cli, width, height)
        stream = ZRLEStream()

        first = (1, 1, 1)
        second = (2, 2, 2)
        first_rect = zrle_rect(0, 0, width, height, pack("!B", 1) + _cpixel(*first), stream)
        second_rect = zrle_rect(0, 0, width, height, pack("!B", 1) + _cpixel(*second), stream)
        self.cli.dataReceived(framebuffer_update([first_rect]))
        assert_pixels(self, self.cli.screen, [first] * (width * height))

        self.cli.dataReceived(framebuffer_update([second_rect]))
        assert_pixels(self, self.cli.screen, [second] * (width * height))

    def test_zrle_high_cpixel_placement_reads_three_bytes_at_the_high_end(self) -> None:
        """cpixel_offset generalises beyond the default fixture's low
        placement -- proves the fix for the hardcoded-layout defect this
        decoder replaces (rfb.py's old ``cpixel()``).
        """
        pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 8, 16, 24)
        width = height = 2
        self.cli.dataReceived(b"RFB 003.003\n")
        self.cli.dataReceived(pack("!I", rfb.AuthTypes.NONE))
        server_init = pack("!HH16sI", width, height, pixel_format.to_bytes(), 0)
        self.cli.dataReceived(server_init)

        colour = (5, 6, 7)
        body = pack("!B", 1) + _cpixel(*colour)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        assert_pixels(self, self.cli.screen, [colour] * (width * height))

    def test_zrle_palette_over_16_is_a_protocol_error(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        body = pack("!B", 17)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()

    def test_zrle_truncated_tile_data_is_a_protocol_error(self) -> None:
        width = height = 8
        handshake(self.cli, width, height)
        self.cli.vncProtocolError = mock.Mock()

        # Declares a raw tile but the compressed payload has nothing after
        # the subencoding byte.
        body = pack("!B", 0)
        self.cli.dataReceived(
            framebuffer_update([zrle_rect(0, 0, width, height, body)])
        )

        self.cli.vncProtocolError.assert_called_once()
        self.cli.transport.loseConnection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
