"""CopyRect. RFC 6143 section 7.7.2."""
from __future__ import annotations

from struct import unpack
from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import ClientDecoder


class CopyRectDecoder(ClientDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.COPY_RECTANGLE

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        block = yield 4
        srcx, srcy = unpack("!HH", block)
        x, y, width, height = rect
        client.copyRectangle(srcx, srcy, x, y, width, height)
