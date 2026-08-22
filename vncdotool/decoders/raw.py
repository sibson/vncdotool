"""Raw encoding. RFC 6143 section 7.7.1."""
from __future__ import annotations

from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import PixelDecoder
from .buffer import RectBuffer


class RawDecoder(PixelDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.RAW

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        data = yield target.width * target.height * target.bypp
        target.blit(0, 0, target.width, target.height, data)
