"""Adding an encoding is a module beside this one plus an entry in DECODERS;
rfb.py is not told the encoding exists. specs/decoder-architecture.md.
"""
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
    Encoding.RAW: RawDecoder,
    Encoding.COPY_RECTANGLE: CopyRectDecoder,
}


def build() -> Dict[Encoding, Decoder]:
    """One set of decoders, for one connection."""
    return {encoding: cls() for encoding, cls in DECODERS.items()}


__all__ = [
    "ClientDecoder",
    "ControlDecoder",
    "DECODERS",
    "build",
    "DecodeError",
    "Decoder",
    "PixelDecoder",
    "RectBuffer",
]
