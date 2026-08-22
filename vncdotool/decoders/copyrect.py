"""CopyRect. RFC 6143 section 7.7.2."""
from __future__ import annotations

from struct import unpack
from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import ClientDecoder
from .errors import DecodeError


class CopyRectDecoder(ClientDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.COPY_RECTANGLE

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        block = yield 4
        srcx, srcy = unpack("!HH", block)
        x, y, width, height = rect
        # A crop running off the framebuffer is zero-filled rather than
        # refused, so an unchecked source pastes black and the screenshot
        # lies about what the server sent.
        if srcx + width > client.width or srcy + height > client.height:
            raise DecodeError(
                f"copy source ({srcx},{srcy},{width},{height}) is outside a "
                f"{client.width}x{client.height} framebuffer"
            )
        client.copyRectangle(srcx, srcy, x, y, width, height)
