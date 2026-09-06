from __future__ import annotations

import io
import zlib
from functools import lru_cache
from typing import ClassVar, Generator, List, Optional, Tuple

from PIL import Image

from ..const import JPEG_QUALITY_ENCODINGS, Encoding
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

JPEG_QUALITY_LEVELS = frozenset(JPEG_QUALITY_ENCODINGS)

# Below this height*rowSize, data arrives raw (specs/tight-wire.md section 6).
MIN_TO_COMPRESS = 12

# Exempts Fill: TigerVNC before 1.16.0 sent wider Fill rects (section 7).
MAX_WIDTH = 2048


# A palette entry is one TPIXEL, so bpp of 8/16/24/32 covers every width.
_BAND_MODES = {2: "LA", 3: "RGB", 4: "RGBA"}


@lru_cache(maxsize=64)
def _mono_table(zero: bytes, one: bytes) -> Tuple[bytes, ...]:
    """Each of the 256 bytes a 1-bit row can hold, as its 8 pixels, MSB first."""
    return tuple(
        b"".join(one if byte & (0x80 >> bit) else zero for bit in range(8))
        for byte in range(256)
    )


@lru_cache(maxsize=64)
def _palette_tables(palette: Tuple[bytes, ...]) -> Tuple[Tuple[bytes, ...], bytes]:
    """One 256-byte translation table per channel, and the indices the palette defines."""
    size = len(palette)
    channels = tuple(
        bytes(entry[offset] for entry in palette) + bytes(256 - size)
        for offset in range(len(palette[0]))
    )
    return channels, bytes(range(size))


def _output_format(pixel_format: PixelFormat) -> PixelFormat:
    if tpixel_bytes(pixel_format) == 3:
        return TPIXEL_FORMAT
    return pixel_format


class TightDecoder(WholeRectDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.TIGHT

    def __init__(self) -> None:
        # TigerVNC and TurboVNC use the four streams differently (section 9).
        self._streams: List[Optional["zlib._Decompress"]] = [None] * STREAMS
        self._jpeg_offered = False

    def encodingsOffered(self, encodings: frozenset[Encoding]) -> None:
        self._jpeg_offered = bool(encodings & JPEG_QUALITY_LEVELS)

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
            if not self._jpeg_offered:
                raise DecodeError(
                    "Tight JpegCompression arrived without a JPEG Quality Level "
                    "offered; it is lossy, so the capture would not be exact"
                )
            # No filter byte, no zlib and no MIN_TO_COMPRESS rule (specs/tight-wire.md section 4).
            length = yield from self._compactLength()
            return self._decodeJpeg(bytes((yield length)), width, height), TPIXEL_FORMAT

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
        palette: Optional[Tuple[bytes, ...]] = None

        if filter_id == FILTER_COPY:
            row_size = width * tbytes
        elif filter_id == FILTER_PALETTE:
            # The byte is the palette size minus one, so 1 means two colours.
            palette_size = (yield 1)[0] + 1
            raw = yield palette_size * tbytes
            # A tuple so the derived translation tables can be cached on it.
            palette = tuple(raw[i * tbytes:(i + 1) * tbytes] for i in range(palette_size))
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

    @staticmethod
    def _decodeJpeg(block: bytes, width: int, height: int) -> bytes:
        try:
            image = Image.open(io.BytesIO(block))
            # TurboVNC's -subsamp gray sends 1 component, not 3 (section 4).
            rgb = image.convert("RGB")
        except Exception as exc:
            # Pillow raises DecompressionBombError, not OSError, on an implausible header.
            raise DecodeError(f"Tight JPEG rectangle did not decode: {exc}") from None
        if rgb.size != (width, height):
            raise DecodeError(
                f"Tight JPEG rectangle carries a {rgb.width}x{rgb.height} image "
                f"for a {width}x{height} rectangle"
            )
        return rgb.tobytes()

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
        data: bytes, palette: Tuple[bytes, ...], width: int, height: int, row_size: int
    ) -> bytes:
        if not data:
            return b""

        if len(palette) == 2:
            table = _mono_table(palette[0], palette[1])
            pixels = b"".join(map(table.__getitem__, data))
            stride = width * len(palette[0])
            padded = row_size * 8 * len(palette[0])
            if padded == stride:
                return pixels
            # Expanding whole bytes overshoots each row's padding (section 5).
            return b"".join(
                pixels[row * padded:row * padded + stride] for row in range(height)
            )

        channels, defined = _palette_tables(palette)
        # translate() with no table deletes every defined index, so a
        # non-empty result is an index the palette does not have.
        if data.translate(None, defined):
            raise DecodeError(
                f"Tight palette index out of range for a {len(palette)}-colour palette"
            )
        if len(channels) == 1:
            return data.translate(channels[0])
        return Image.merge(
            _BAND_MODES[len(channels)],
            [Image.frombytes("L", (width, height), data.translate(c)) for c in channels],
        ).tobytes()
