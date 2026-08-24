"""DesktopSize and QEMU extended key pseudo-encodings. rfbproto."""
from __future__ import annotations

from typing import ClassVar, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .base import ControlDecoder


class DesktopSizeDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_DESKTOP_SIZE

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        _, _, width, height = rect
        client.updateDesktopSize(width, height)
        return
        yield  # pragma: no cover -- never runs; keeps this a generator


class QemuExtendedKeyDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        client.negotiated_encodings.add(Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
        return
        yield  # pragma: no cover -- never runs; keeps this a generator
