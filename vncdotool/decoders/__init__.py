from __future__ import annotations

from typing import Dict, Type

from ..const import Encoding
from .base import (
    ClientDecoder,
    ControlDecoder,
    Decoder,
    PixelDecoder,
    RectDecoder,
    WholeRectDecoder,
)
from .buffer import RectBuffer
from .control import DesktopSizeDecoder, QemuExtendedKeyDecoder
from .copyrect import CopyRectDecoder
from .cursor import CursorDecoder
from .errors import DecodeError
from .hextile import HextileDecoder
from .raw import RawDecoder
from .rre import CoRREDecoder, RREDecoder
from .zrle import ZRLEDecoder

# Classes, not instances: ZRLE and Tight own a zlib stream that lives for
# one connection (RFC 6143 section 7.7.6), so decoders cannot be shared
# between them even though most decoders hold no state.
DECODERS: Dict[Encoding, Type[Decoder]] = {
    cls.ENCODING: cls
    for cls in (
        RawDecoder,
        CopyRectDecoder,
        RREDecoder,
        CoRREDecoder,
        HextileDecoder,
        ZRLEDecoder,
        CursorDecoder,
        DesktopSizeDecoder,
        QemuExtendedKeyDecoder,
    )
}

# The names --encodings accepts. Registered encodings only: an encoding still
# on rfb.py's own path decodes, but is not offered.
ENCODING_NAMES: Dict[str, Encoding] = {
    "raw": Encoding.RAW,
    "copyrect": Encoding.COPY_RECTANGLE,
    "rre": Encoding.RRE,
    "corre": Encoding.CORRE,
    "hextile": Encoding.HEXTILE,
    "zrle": Encoding.ZRLE,
}


def for_connection() -> Dict[Encoding, Decoder]:
    return {encoding: cls() for encoding, cls in DECODERS.items()}


__all__ = [
    "ClientDecoder",
    "ControlDecoder",
    "DECODERS",
    "DecodeError",
    "Decoder",
    "ENCODING_NAMES",
    "PixelDecoder",
    "RectBuffer",
    "RectDecoder",
    "WholeRectDecoder",
    "for_connection",
]
