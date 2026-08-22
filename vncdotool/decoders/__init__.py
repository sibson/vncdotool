from __future__ import annotations

from typing import Dict, Type

from ..const import Encoding
from .base import ClientDecoder, ControlDecoder, DecodeError, Decoder, PixelDecoder
from .buffer import RectBuffer
from .copyrect import CopyRectDecoder
from .raw import RawDecoder

# Classes, not instances: ZRLE and Tight own a zlib stream that lives for
# one connection (RFC 6143 section 7.7.6), so decoders cannot be shared
# between them even though today's two hold no state.
DECODERS: Dict[Encoding, Type[Decoder]] = {
    cls.ENCODING: cls
    for cls in (
        RawDecoder,
        CopyRectDecoder,
    )
}


def for_connection() -> Dict[Encoding, Decoder]:
    return {encoding: cls() for encoding, cls in DECODERS.items()}


__all__ = [
    "ClientDecoder",
    "ControlDecoder",
    "DECODERS",
    "DecodeError",
    "Decoder",
    "PixelDecoder",
    "RectBuffer",
    "for_connection",
]
