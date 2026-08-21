"""Hextile: 16x16 tiles, each raw or a background plus subrectangles.

RFC 6143 section 7.7.4.
"""
from __future__ import annotations

from typing import ClassVar, Iterator

from ..const import Encoding, HextileEncoding
from ..pixelformat import PixelFormat
from .base import PixelDecoder
from .buffer import RectBuffer
from .errors import DecodeError

TILE = 16


class HextileDecoder(PixelDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.HEXTILE

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        bypp = target.bypp
        # Both carry over from the previous tile, but not across a raw tile,
        # and the foreground not across a coloured-subrectangle one either.
        background = foreground = b""

        for ty in range(0, target.height, TILE):
            th = min(TILE, target.height - ty)
            for tx in range(0, target.width, TILE):
                tw = min(TILE, target.width - tx)

                subencoding = HextileEncoding((yield 1)[0])
                if subencoding & HextileEncoding.RAW:
                    target.blit(tx, ty, tw, th, (yield tw * th * bypp))
                    background = foreground = b""
                    continue

                wanted = 0
                if subencoding & HextileEncoding.BACKGROUND_SPECIFIED:
                    wanted += bypp
                if subencoding & HextileEncoding.FOREGROUND_SPECIFIED:
                    wanted += bypp
                if subencoding & HextileEncoding.ANY_SUBRECTS:
                    wanted += 1
                block = (yield wanted) if wanted else b""

                pos = 0
                if subencoding & HextileEncoding.BACKGROUND_SPECIFIED:
                    background = block[:bypp]
                    pos = bypp
                if not background:
                    raise DecodeError(f"tile at ({tx},{ty}) has no background, and no tile before it set one")
                target.fill(tx, ty, tw, th, background)

                if subencoding & HextileEncoding.FOREGROUND_SPECIFIED:
                    foreground = block[pos:pos + bypp]
                    pos += bypp
                if not (subencoding & HextileEncoding.ANY_SUBRECTS):
                    continue

                count = block[pos]
                coloured = bool(subencoding & HextileEncoding.SUBRECTS_COLORED)
                # A tile may set AnySubrects and then declare none, which
                # needs no foreground however many tiles came before it.
                if count and not coloured and not foreground:
                    raise DecodeError(f"tile at ({tx},{ty}) has no foreground, and no tile before it set one")

                size = bypp + 2 if coloured else 2
                data = yield size * count
                for offset in range(0, len(data), size):
                    colour = foreground
                    if coloured:
                        colour = data[offset:offset + bypp]
                        offset += bypp
                    xy, wh = data[offset], data[offset + 1]
                    sx, sy = xy >> 4, xy & 0xF
                    sw, sh = (wh >> 4) + 1, (wh & 0xF) + 1
                    # Against the tile, not the rectangle: a subrectangle
                    # overflowing its tile still lands inside the buffer, so
                    # nothing downstream would notice.
                    if sx + sw > tw or sy + sh > th:
                        raise DecodeError(
                            f"subrectangle ({sx},{sy},{sw},{sh}) overflows a {tw}x{th} tile"
                        )
                    target.fill(tx + sx, ty + sy, sw, sh, colour)

                if coloured:
                    foreground = b""
