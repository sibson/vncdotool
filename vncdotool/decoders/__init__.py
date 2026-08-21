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
from .rre import CoRREDecoder, RREDecoder

# Classes, not instances: ZRLE and Tight own a zlib stream that lives for
# one connection (RFC 6143 section 7.7.6), so decoders cannot be shared
# between them even though today's four hold no state.
DECODERS: Dict[Encoding, Type[Decoder]] = {
    Encoding.RAW: RawDecoder,
    Encoding.COPY_RECTANGLE: CopyRectDecoder,
    Encoding.RRE: RREDecoder,
    Encoding.CORRE: CoRREDecoder,
}

# The names --encodings accepts. Registered encodings only: what is still on
# rfb.py's own path decodes, but is not offered until its phase migrates it.
ENCODING_NAMES: Dict[str, Encoding] = {
    "raw": Encoding.RAW,
    "copyrect": Encoding.COPY_RECTANGLE,
    "rre": Encoding.RRE,
    "corre": Encoding.CORRE,
}


def build() -> Dict[Encoding, Decoder]:
    """One set of decoders, for one connection."""
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
    "build",
]
