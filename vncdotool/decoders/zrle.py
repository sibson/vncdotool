"""ZRLE. RFC 6143 section 7.7.6."""
from __future__ import annotations

import zlib
from struct import unpack
from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat, cpixel_bytes, cpixel_offset
from .base import PixelDecoder
from .buffer import RectBuffer
from .errors import DecodeError

TILE = 64


def _unpack_row(it: Iterator[int], width: int, bits: int) -> list[int]:
    """One tile row's packed palette indices, ``bits`` each, MSB-first.

    RFC 6143 7.7.6: "padding bits are used to align each row to an exact
    number of bytes" -- so a row is its own byte-aligned unit and any
    leftover bits at the end of its last byte are not part of the next
    row. A plain loop, not a generator: see the comment on cpixel() below
    for why next(it) can't run inside one here.
    """
    per_byte = 8 // bits
    mask = (1 << bits) - 1
    indices: list[int] = []
    while len(indices) < width:
        b = next(it)
        for slot in range(per_byte):
            if len(indices) == width:
                break
            shift = 8 - bits - slot * bits
            indices.append((b >> shift) & mask)
    return indices


class ZRLEDecoder(PixelDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.ZRLE

    def __init__(self) -> None:
        # RFC 6143 7.7.6: one zlib stream per connection, rectangles decoded
        # strictly in order. for_connection() gives each connection its own
        # decoder instance, so the stream lives exactly that long (R7).
        self._zlib_stream = zlib.decompressobj(0)

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        length_block = yield 4
        (compressed_bytes,) = unpack("!L", length_block)
        block = yield compressed_bytes

        data = self._zlib_stream.decompress(block)
        it = iter(data)
        cbytes = cpixel_bytes(pixel_format)
        coffset = cpixel_offset(pixel_format)
        bypp = target.bypp

        def cpixel() -> bytes:
            # A plain loop, not a generator expression: a genexpr is itself
            # a generator frame, so a StopIteration raised by next(it) inside
            # one is converted to RuntimeError (PEP 479) before it ever
            # reaches decodePixels' own except clause below.
            raw = bytearray(cbytes)
            for i in range(cbytes):
                raw[i] = next(it)
            if cbytes == bypp:
                return bytes(raw)
            # CPIXEL is narrower than a PIXEL: place its bytes at the
            # negotiated offset and leave the rest zero.
            buf = bytearray(bypp)
            buf[coffset:coffset + cbytes] = raw
            return bytes(buf)

        def do_rle(pixel: bytes, pixel_data: bytearray) -> int:
            run_length_next = next(it)
            run_length = run_length_next
            while run_length_next == 255:
                run_length_next = next(it)
                run_length += run_length_next
            pixel_data.extend(pixel * (run_length + 1))
            return run_length + 1

        try:
            for ty in range(0, target.height, TILE):
                th = min(TILE, target.height - ty)
                for tx in range(0, target.width, TILE):
                    tw = min(TILE, target.width - tx)
                    pixels_in_tile = tw * th

                    subencoding = next(it)
                    palette_size = subencoding & 127

                    if subencoding & 0x80:
                        pixel_data = bytearray()
                        num_pixels = 0
                        if palette_size == 0:
                            while num_pixels < pixels_in_tile:
                                num_pixels += do_rle(cpixel(), pixel_data)
                        else:
                            palette = [cpixel() for _ in range(palette_size)]
                            while num_pixels < pixels_in_tile:
                                palette_index = next(it)
                                if palette_index & 0x80:
                                    num_pixels += do_rle(palette[palette_index & 0x7F], pixel_data)
                                else:
                                    pixel_data.extend(palette[palette_index])
                                    num_pixels += 1
                        if num_pixels != pixels_in_tile:
                            raise DecodeError(
                                f"ZRLE RLE tile at ({tx},{ty}) decoded {num_pixels} "
                                f"pixels, wanted {pixels_in_tile}"
                            )
                        target.blit(tx, ty, tw, th, bytes(pixel_data))
                    elif palette_size == 0:
                        pixel_data = bytearray()
                        for _ in range(pixels_in_tile):
                            pixel_data.extend(cpixel())
                        target.blit(tx, ty, tw, th, bytes(pixel_data))
                    elif palette_size == 1:
                        target.fill(tx, ty, tw, th, cpixel())
                    elif palette_size > 16:
                        raise DecodeError(f"ZRLE palette of size {palette_size} is not allowed")
                    else:
                        palette = [cpixel() for _ in range(palette_size)]
                        bits = 1 if palette_size == 2 else (2 if palette_size <= 4 else 4)
                        pixel_data = bytearray()
                        for _ in range(th):
                            for palette_index in _unpack_row(it, tw, bits):
                                pixel_data.extend(palette[palette_index])
                        target.blit(tx, ty, tw, th, bytes(pixel_data))
        except StopIteration:
            raise DecodeError("ZRLE tile data ended before the rectangle did") from None
