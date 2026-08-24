"""Cursor pseudo-encoding. rfbproto."""
from __future__ import annotations

from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import ClientDecoder


class CursorDecoder(ClientDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_CURSOR

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        x, y, width, height = rect
        pixel_len = width * height * pixel_format.bypp
        mask_len = ((width + 7) // 8) * height
        block = yield pixel_len + mask_len
        client.updateCursor(x, y, width, height, block[:pixel_len], block[pixel_len:])
