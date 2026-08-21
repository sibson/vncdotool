"""Raw encoding. RFC 6143 section 7.7.1."""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from ..rfb import PixelFormat
    from .buffer import RectBuffer


class RawDecoder:
    def decode(self, target: "RectBuffer", pixel_format: "PixelFormat") -> Iterator[int]:
        data = yield target.width * target.height * target.bypp
        target.blit(0, 0, target.width, target.height, data)

    def output_format(self, pixel_format: "PixelFormat") -> "PixelFormat":
        return pixel_format
