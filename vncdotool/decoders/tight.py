from __future__ import annotations

import zlib
from typing import ClassVar, Generator, List, Optional

from ..const import Encoding
from ..pixelformat import TPIXEL_FORMAT, PixelFormat, tpixel_bytes
from .base import WholeRectDecoder
from .errors import DecodeError

STREAMS = 4

FILL = 0x08
JPEG = 0x09
BASIC_WITHOUT_ZLIB = (0x0A, 0x0E)
EXPLICIT_FILTER = 0x04

FILTER_COPY = 0
FILTER_PALETTE = 1
FILTER_GRADIENT = 2

# Below this height*rowSize, data arrives raw (specs/tight-wire.md section 6).
MIN_TO_COMPRESS = 12

# Exempts Fill: TigerVNC before 1.16.0 sent wider Fill rects (section 7).
MAX_WIDTH = 2048


def _output_format(pixel_format: PixelFormat) -> PixelFormat:
    if tpixel_bytes(pixel_format) == 3:
        return TPIXEL_FORMAT
    return pixel_format


class TightDecoder(WholeRectDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.TIGHT

    def __init__(self) -> None:
        # TigerVNC and TurboVNC use the four streams differently (section 9).
        self._streams: List[Optional["zlib._Decompress"]] = [None] * STREAMS

    def decodeRect(
        self, width: int, height: int, pixel_format: PixelFormat
    ) -> Generator[int, bytes, tuple[bytes, PixelFormat]]:
        comp_ctl = (yield 1)[0]

        # Reset bits apply even to Fill and JPEG (specs/tight-wire.md section 2).
        for stream_id in range(STREAMS):
            if comp_ctl & (1 << stream_id):
                self._streams[stream_id] = None
        comp_ctl >>= 4

        if comp_ctl == FILL:
            pixel = yield tpixel_bytes(pixel_format)
            return bytes(pixel) * (width * height), _output_format(pixel_format)

        if width > MAX_WIDTH:
            raise DecodeError(
                f"Tight rectangle is {width} pixels wide, over the {MAX_WIDTH} limit"
            )

        if comp_ctl == JPEG:
            raise DecodeError("Tight JpegCompression is not supported")

        if comp_ctl & 0x08:
            if comp_ctl in BASIC_WITHOUT_ZLIB:
                raise DecodeError(
                    "Tight BasicCompression Without Zlib, which needs the -317 "
                    "pseudo-encoding this client never advertises"
                )
            raise DecodeError(f"Tight compression control 0x{comp_ctl:x}0 is not defined")

        return (yield from self._decodeBasic(comp_ctl, width, height, pixel_format))

    def _decodeBasic(
        self, comp_ctl: int, width: int, height: int, pixel_format: PixelFormat
    ) -> Generator[int, bytes, tuple[bytes, PixelFormat]]:
        if comp_ctl & EXPLICIT_FILTER:
            filter_id = (yield 1)[0]
        else:
            filter_id = FILTER_COPY

        stream_id = comp_ctl & 0x03
        tbytes = tpixel_bytes(pixel_format)
        palette: Optional[List[bytes]] = None

        if filter_id == FILTER_COPY:
            row_size = width * tbytes
        elif filter_id == FILTER_PALETTE:
            # The byte is the palette size minus one, so 1 means two colours.
            palette_size = (yield 1)[0] + 1
            raw = yield palette_size * tbytes
            palette = [raw[i * tbytes:(i + 1) * tbytes] for i in range(palette_size)]
            # 2 colours pack 1 bit/pixel padded to a byte per row (section 5).
            row_size = (width + 7) // 8 if palette_size == 2 else width
        elif filter_id == FILTER_GRADIENT:
            raise DecodeError("Tight GradientFilter is not supported")
        else:
            raise DecodeError(f"Tight filter id {filter_id} is not defined")

        data_size = height * row_size
        if data_size == 0:
            data = b""
        elif data_size < MIN_TO_COMPRESS:
            data = bytes((yield data_size))
        else:
            length = yield from self._compactLength()
            data = self._decompress(stream_id, (yield length), data_size)

        if palette is None:
            return data, _output_format(pixel_format)
        return (
            self._unpalette(data, palette, width, height, row_size),
            _output_format(pixel_format),
        )

    def _compactLength(self) -> Generator[int, bytes, int]:
        """1-3 bytes, 7 bits each except the third, which carries 8 (section 6)."""
        byte = (yield 1)[0]
        length = byte & 0x7F
        if byte & 0x80:
            byte = (yield 1)[0]
            length |= (byte & 0x7F) << 7
            if byte & 0x80:
                length |= (yield 1)[0] << 14
        return length

    def _decompress(self, stream_id: int, block: bytes, size: int) -> bytes:
        stream = self._streams[stream_id]
        if stream is None:
            stream = self._streams[stream_id] = zlib.decompressobj()

        out = bytearray()
        tail = bytes(block)
        while True:
            remaining = size - len(out)
            if remaining > 0:
                out += stream.decompress(tail, remaining)
                tail = stream.unconsumed_tail
                if not tail:
                    break
                continue
            # A sync-flush marker decompresses to no bytes (section 9).
            if stream.decompress(tail, 1):
                raise DecodeError(
                    f"Tight stream {stream_id} carries more than the {size} bytes "
                    "this rectangle declares"
                )
            break

        if len(out) != size:
            raise DecodeError(
                f"Tight stream {stream_id} produced {len(out)} bytes, wanted {size}"
            )
        return bytes(out)

    @staticmethod
    def _unpalette(
        data: bytes, palette: List[bytes], width: int, height: int, row_size: int
    ) -> bytes:
        pixels = bytearray()
        try:
            if len(palette) == 2:
                for row in range(height):
                    base = row * row_size
                    for x in range(width):
                        byte = data[base + (x >> 3)]
                        pixels += palette[(byte >> (7 - (x & 7))) & 1]
            else:
                for index in data:
                    pixels += palette[index]
        except IndexError:
            raise DecodeError(
                f"Tight palette index out of range for a {len(palette)}-colour palette"
            ) from None
        return bytes(pixels)
