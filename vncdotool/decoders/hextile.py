"""Hextile. RFC 6143 section 7.7.4."""
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
        # IntFlag's & allocates a new flag object per test.
        raw_bit = HextileEncoding.RAW.value
        background_bit = HextileEncoding.BACKGROUND_SPECIFIED.value
        foreground_bit = HextileEncoding.FOREGROUND_SPECIFIED.value
        subrects_bit = HextileEncoding.ANY_SUBRECTS.value
        coloured_bit = HextileEncoding.SUBRECTS_COLORED.value
        # Background and foreground carry over from the previous tile, but
        # neither across a raw tile, and the foreground not across a
        # coloured-subrectangle tile either.
        background = foreground = b""

        for ty in range(0, target.height, TILE):
            th = min(TILE, target.height - ty)
            for tx in range(0, target.width, TILE):
                tw = min(TILE, target.width - tx)

                subencoding = (yield 1)[0]
                if subencoding & raw_bit:
                    target.blit(tx, ty, tw, th, (yield tw * th * bypp))
                    background = foreground = b""
                    continue

                wanted = 0
                if subencoding & background_bit:
                    wanted += bypp
                if subencoding & foreground_bit:
                    wanted += bypp
                if subencoding & subrects_bit:
                    wanted += 1
                block = (yield wanted) if wanted else b""

                pos = 0
                if subencoding & background_bit:
                    background = block[:bypp]
                    pos = bypp
                if not background:
                    raise DecodeError(f"tile at ({tx},{ty}) has no background, and no tile before it set one")
                target.fill(tx, ty, tw, th, background)

                if subencoding & foreground_bit:
                    foreground = block[pos:pos + bypp]
                    pos += bypp
                if not subencoding & subrects_bit:
                    continue

                count = block[pos]
                coloured = bool(subencoding & coloured_bit)
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
