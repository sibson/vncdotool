from __future__ import annotations

from typing import Dict, Type

from ..const import Encoding
from .base import ClientDecoder, Decoder, PixelDecoder
from .buffer import RectBuffer
from .copyrect import CopyRectDecoder
from .errors import DecodeError
from .raw import RawDecoder
from .rre import CoRREDecoder, RREDecoder

# Classes, not instances: ZRLE and Tight own a zlib stream that lives for
# one connection (RFC 6143 section 7.7.6), so decoders cannot be shared
# between them even though today's four hold no state.
DECODERS: Dict[Encoding, Type[Decoder]] = {
    cls.ENCODING: cls
    for cls in (
        RawDecoder,
        CopyRectDecoder,
        RREDecoder,
        CoRREDecoder,
    )
}

# The names --encodings accepts. Registered encodings only: an encoding still
# on rfb.py's own path decodes, but is not offered.
ENCODING_NAMES: Dict[str, Encoding] = {
    "raw": Encoding.RAW,
    "copyrect": Encoding.COPY_RECTANGLE,
    "rre": Encoding.RRE,
    "corre": Encoding.CORRE,
}


def for_connection() -> Dict[Encoding, Decoder]:
    return {encoding: cls() for encoding, cls in DECODERS.items()}


__all__ = [
    "ClientDecoder",
    "DECODERS",
    "DecodeError",
    "Decoder",
    "ENCODING_NAMES",
    "PixelDecoder",
    "RectBuffer",
    "for_connection",
]
