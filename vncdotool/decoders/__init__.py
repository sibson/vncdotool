"""The decoder registry.

Adding an encoding is a module beside this one plus an entry in DECODERS;
rfb.py is not told the encoding exists. specs/decoder-architecture.md.
"""
from __future__ import annotations

from typing import Dict, Union

from ..const import Encoding
from .base import ClientDecoder, ControlDecoder, DecodeError, PixelDecoder
from .buffer import RectBuffer
from .copyrect import CopyRectDecoder
from .raw import RawDecoder

Decoder = Union[PixelDecoder, ClientDecoder, ControlDecoder]

DECODERS: Dict[Encoding, Decoder] = {
    Encoding.RAW: RawDecoder(),
    Encoding.COPY_RECTANGLE: CopyRectDecoder(),
}

__all__ = [
    "ClientDecoder",
    "ControlDecoder",
    "DECODERS",
    "DecodeError",
    "Decoder",
    "PixelDecoder",
    "RectBuffer",
]
