"""ZRLE. RFC 6143 section 7.7.6."""
from __future__ import annotations

import zlib
from functools import lru_cache
from struct import unpack
from typing import ClassVar, Iterator, Optional, Tuple

from ..const import Encoding
from ..pixelformat import PixelFormat, cpixel_bytes, cpixel_offset
from .base import PixelDecoder
from .buffer import RectBuffer
from .errors import DecodeError

TILE = 64


def _expand_cpixels(raw: bytes, count: int, cbytes: int, bypp: int, coffset: int) -> bytes:
    """``count`` consecutive CPIXELs widened to PIXELs.

    One strided slice assignment per CPIXEL byte, so the widening runs at
    C speed. The bytes a CPIXEL does not carry stay zero, and which three
    of the PIXEL's bytes it does carry is ``coffset``'s business (RFC 6143
    7.7.5 gives the rule two placements).
    """
    if cbytes == bypp:
        return raw
    out = bytearray(count * bypp)
    for i in range(cbytes):
        out[coffset + i::bypp] = raw[i::cbytes]
    return bytes(out)


@lru_cache(maxsize=64)
def _index_tables(
    palette: Tuple[bytes, ...], bits: int
) -> Tuple[Tuple[bytes, ...], Optional[Tuple[bytes, ...]]]:
    """Each of the 256 bytes a packed-index row can hold, as its pixels.

    The second table marks the same pixels with one byte apiece, set where
    the index behind a pixel is one the palette does not define. It is None
    when the palette fills the index space, where no byte can hold a bad
    index.
    """
    per_byte = 8 // bits
    mask = (1 << bits) - 1
    size = len(palette)
    blank = bytes(len(palette[0]))

    expanded = []
    undefined = []
    for byte in range(256):
        indices = [(byte >> (8 - bits - slot * bits)) & mask for slot in range(per_byte)]
        expanded.append(b"".join(palette[i] if i < size else blank for i in indices))
        undefined.append(bytes(1 if i >= size else 0 for i in indices))

    if size == 1 << bits:
        return tuple(expanded), None
    return tuple(expanded), tuple(undefined)


class ZRLEDecoder(PixelDecoder):
    ENCODING: ClassVar[Encoding] = Encoding.ZRLE

    def __init__(self) -> None:
        # RFC 6143 7.7.6: one zlib stream per connection, rectangles decoded
        # strictly in order. for_connection() gives each connection its own
        # decoder instance, so the stream lives exactly that long.
        self._zlib_stream = zlib.decompressobj(0)

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        length_block = yield 4
        (compressed_bytes,) = unpack("!L", length_block)
        block = yield compressed_bytes

        data = self._zlib_stream.decompress(block)
        end = len(data)
        pos = 0
        cbytes = cpixel_bytes(pixel_format)
        coffset = cpixel_offset(pixel_format)
        bypp = target.bypp

        def short(tx: int, ty: int) -> DecodeError:
            return DecodeError(
                f"ZRLE tile at ({tx},{ty}) ran past the end of the rectangle's tile data"
            )

        for ty in range(0, target.height, TILE):
            th = min(TILE, target.height - ty)
            for tx in range(0, target.width, TILE):
                tw = min(TILE, target.width - tx)
                pixels_in_tile = tw * th

                if pos >= end:
                    raise short(tx, ty)
                subencoding = data[pos]
                pos += 1
                palette_size = subencoding & 127

                # RFC 6143 7.7.6 caps a packed palette at 16 colours; the RLE
                # form's own limit is the 127 the size field can hold.
                if not subencoding & 0x80 and palette_size > 16:
                    raise DecodeError(f"ZRLE palette of size {palette_size} is not allowed")

                palette: Tuple[bytes, ...] = ()
                if palette_size:
                    need = palette_size * cbytes
                    if pos + need > end:
                        raise short(tx, ty)
                    flat = _expand_cpixels(
                        data[pos:pos + need], palette_size, cbytes, bypp, coffset
                    )
                    pos += need
                    palette = tuple(
                        flat[i * bypp:(i + 1) * bypp] for i in range(palette_size)
                    )

                if subencoding & 0x80:
                    pixel_data = bytearray()
                    num_pixels = 0
                    while num_pixels < pixels_in_tile:
                        if palette_size == 0:
                            if pos + cbytes > end:
                                raise short(tx, ty)
                            pixel = _expand_cpixels(
                                data[pos:pos + cbytes], 1, cbytes, bypp, coffset
                            )
                            pos += cbytes
                        else:
                            if pos >= end:
                                raise short(tx, ty)
                            index = data[pos]
                            pos += 1
                            entry = index & 0x7F
                            if entry >= palette_size:
                                raise DecodeError(
                                    f"ZRLE palette index {entry} is past the end of a "
                                    f"{palette_size}-colour palette"
                                )
                            pixel = palette[entry]
                            if not index & 0x80:
                                pixel_data += pixel
                                num_pixels += 1
                                continue

                        # A run length is a sum: every 255 says another byte
                        # follows, and the total is one less than the run.
                        if pos >= end:
                            raise short(tx, ty)
                        part = data[pos]
                        pos += 1
                        run_length = part
                        while part == 255:
                            if pos >= end:
                                raise short(tx, ty)
                            part = data[pos]
                            pos += 1
                            run_length += part
                        pixel_data += pixel * (run_length + 1)
                        num_pixels += run_length + 1

                    if num_pixels != pixels_in_tile:
                        raise DecodeError(
                            f"ZRLE RLE tile at ({tx},{ty}) decoded {num_pixels} "
                            f"pixels, wanted {pixels_in_tile}"
                        )
                    target.blit(tx, ty, tw, th, bytes(pixel_data))
                elif palette_size == 0:
                    need = pixels_in_tile * cbytes
                    if pos + need > end:
                        raise short(tx, ty)
                    target.blit(tx, ty, tw, th, _expand_cpixels(
                        data[pos:pos + need], pixels_in_tile, cbytes, bypp, coffset
                    ))
                    pos += need
                elif palette_size == 1:
                    target.fill(tx, ty, tw, th, palette[0])
                else:
                    bits = 1 if palette_size == 2 else (2 if palette_size <= 4 else 4)
                    expanded, undefined = _index_tables(palette, bits)
                    per_byte = 8 // bits
                    # RFC 6143 7.7.6: "padding bits are used to align each
                    # row to an exact number of bytes" -- so a row is its own
                    # byte-aligned unit, and expanding whole bytes overshoots
                    # into padding that the next row does not continue.
                    row_size = (tw + per_byte - 1) // per_byte
                    stride = tw * bypp
                    if pos + row_size * th > end:
                        raise short(tx, ty)

                    rows = []
                    for _ in range(th):
                        packed = data[pos:pos + row_size]
                        pos += row_size
                        if undefined is not None and any(
                            b"".join(map(undefined.__getitem__, packed))[:tw]
                        ):
                            raise DecodeError(
                                f"ZRLE palette index is past the end of a "
                                f"{palette_size}-colour palette"
                            )
                        rows.append(b"".join(map(expanded.__getitem__, packed))[:stride])
                    target.blit(tx, ty, tw, th, b"".join(rows))
