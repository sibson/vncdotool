"""Raw encoding. RFC 6143 section 7.7.1."""
from __future__ import annotations

from typing import Any, ClassVar, Generator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import Outcome, PixelDecoder, Rect, painted


class RawDecoder(PixelDecoder):
    """Raw's wire bytes are already its output bytes, in order, in one read,
    so it hands them to the pump rather than filling a buffer it would only
    copy back out. See specs/decoder-architecture.md, "Benchmark" (N1).
    """

    ENCODING: ClassVar[Encoding] = Encoding.RAW

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        client.requireFits(rect[2], rect[3])
        output_format = self.output_format(pixel_format)
        data = yield rect[2] * rect[3] * output_format.bypp
        return painted(data, output_format)
