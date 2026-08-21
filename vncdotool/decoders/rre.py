"""RRE and CoRRE: a background fill, then a list of coloured subrectangles.

RFC 6143 section 7.7.3 for RRE. CoRRE is not in RFC 6143; rfbproto has it,
and it is RRE with U8 subrectangle coordinates, which is why it inherits.
"""
from __future__ import annotations

from struct import Struct, unpack
from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import PixelDecoder
from .buffer import RectBuffer
from .errors import DecodeError


class RREDecoder(PixelDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.RRE
    COORDS: ClassVar[Struct] = Struct("!HHHH")

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        bypp = target.bypp
        header = yield 4 + bypp
        (count,) = unpack("!I", header[:4])
        target.fill(0, 0, target.width, target.height, header[4:])
        if not count:
            return

        # The count is a U32 and the specs do not bound it, but a
        # subrectangle covers at least one pixel and this encoding exists to
        # be smaller than Raw, so more of them than the rectangle has pixels
        # is malformed rather than merely wasteful.
        if count > target.width * target.height:
            raise DecodeError(
                f"{count} subrectangles in a {target.width}x{target.height} rectangle"
            )

        size = bypp + self.COORDS.size
        data = yield size * count
        for pos in range(0, len(data), size):
            x, y, width, height = self.COORDS.unpack_from(data, pos + bypp)
            target.fill(x, y, width, height, data[pos:pos + bypp])


class CoRREDecoder(RREDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.CORRE
    COORDS: ClassVar[Struct] = Struct("!BBBB")
