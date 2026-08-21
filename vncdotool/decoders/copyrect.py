"""CopyRect: a framebuffer-to-framebuffer blit.

RFC 6143 section 7.7.2. It reads no pixel data, and its source is the
framebuffer rather than the stream, so it is a ClientDecoder.
"""
from __future__ import annotations

from struct import unpack
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from ..rfb import PixelFormat, Rect


class CopyRectDecoder:
    def decode(
        self, client: object, rect: "Rect", pixel_format: "PixelFormat"
    ) -> Iterator[int]:
        block = yield 4
        srcx, srcy = unpack("!HH", block)
        x, y, width, height = rect
        client.copyRectangle(srcx, srcy, x, y, width, height)
