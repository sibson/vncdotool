from __future__ import annotations

from typing import Dict, Type

from ..const import Encoding
from .base import (
    CHANGED,
    NOTHING,
    ClientDecoder,
    ControlDecoder,
    Decoder,
    Outcome,
    Paste,
    PixelDecoder,
    Rect,
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
from .tight import TightDecoder
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
        TightDecoder,
        CursorDecoder,
        DesktopSizeDecoder,
        QemuExtendedKeyDecoder,
    )
}

# The names --encodings accepts. Cursor, DesktopSize and QemuExtendedKey are
# registered decoders too, but client.py offers them from its own pseudocursor
# / pseudodesktop / qemu_extended_key flags rather than by name here.
ENCODING_NAMES: Dict[str, Encoding] = {
    "raw": Encoding.RAW,
    "copyrect": Encoding.COPY_RECTANGLE,
    "rre": Encoding.RRE,
    "corre": Encoding.CORRE,
    "hextile": Encoding.HEXTILE,
    "zrle": Encoding.ZRLE,
    "tight": Encoding.TIGHT,
}

DEFAULT_ENCODING_NAMES = ("tight", "zrle", "hextile", "raw")
DEFAULT_ENCODINGS = [ENCODING_NAMES[name] for name in DEFAULT_ENCODING_NAMES]


def for_connection() -> Dict[Encoding, Decoder]:
    return {encoding: cls() for encoding, cls in DECODERS.items()}


__all__ = [
    "CHANGED",
    "ClientDecoder",
    "ControlDecoder",
    "DECODERS",
    "DecodeError",
    "Decoder",
    "ENCODING_NAMES",
    "NOTHING",
    "Outcome",
    "Paste",
    "PixelDecoder",
    "Rect",
    "RectBuffer",
    "WholeRectDecoder",
    "for_connection",
]
