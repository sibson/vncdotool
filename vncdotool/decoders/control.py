"""DesktopSize, ExtendedDesktopSize and QEMU extended key pseudo-encodings.
rfbproto."""
from __future__ import annotations

from struct import unpack_from
from typing import Any, ClassVar, Generator

from ..const import Encoding, Screen
from ..pixelformat import PixelFormat
from .base import NOTHING, ControlDecoder, Decoder, Outcome, Rect

SCREEN_LEN = 16


class DesktopSizeDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_DESKTOP_SIZE

    def decodeForControl(self, client: object, width: int, height: int) -> None:
        client.updateDesktopSize(width, height)


class ExtendedDesktopSizeDecoder(Decoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        reason, result, width, height = rect
        header = yield 4
        count = header[0]
        screens = []
        if count:
            block = yield count * SCREEN_LEN
            for offset in range(0, count * SCREEN_LEN, SCREEN_LEN):
                screens.append(Screen(*unpack_from("!IHHHHI", block, offset)))
        # Receiving one is the only thing that makes SetDesktopSize legal.
        client.negotiated_encodings.add(Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE)
        client.updateExtendedDesktopSize(reason, result, width, height, screens)
        return NOTHING


class QemuExtendedKeyDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT

    def decodeForControl(self, client: object, width: int, height: int) -> None:
        client.negotiated_encodings.add(Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
