"""DesktopSize and QEMU extended key pseudo-encodings. rfbproto."""
from __future__ import annotations

from typing import ClassVar

from ..const import Encoding
from .base import ControlDecoder


class DesktopSizeDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_DESKTOP_SIZE

    def decodeForControl(self, client: object, width: int, height: int) -> None:
        client.updateDesktopSize(width, height)


class QemuExtendedKeyDecoder(ControlDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT

    def decodeForControl(self, client: object, width: int, height: int) -> None:
        client.negotiated_encodings.add(Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
