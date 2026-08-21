"""
Pixel format resolution: :class:`rfb.PixelFormat` -> Pillow raw mode, and the
CPIXEL width/offset rules ZRLE depends on.

Reference:
https://www.rfc-editor.org/rfc/rfc6143#section-7.7.5
https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst (ZRLE Encoding)
"""
from __future__ import annotations

from . import rfb

_32BPP_MODES = {"RGBX", "BGRX", "XRGB", "XBGR"}
_24BPP_MODES = {"RGB", "BGR"}


class UnsupportedPixelFormat(Exception):
    """No Pillow raw mode exists for this :class:`rfb.PixelFormat`."""


def _channel_widths(pixel_format: rfb.PixelFormat) -> tuple[int, int, int]:
    return (
        pixel_format.redmax.bit_length(),
        pixel_format.greenmax.bit_length(),
        pixel_format.bluemax.bit_length(),
    )


def _byte_positions(
    pixel_format: rfb.PixelFormat, nbytes: int
) -> dict[int, str]:
    positions: dict[int, str] = {}
    for shift, channel in (
        (pixel_format.redshift, "R"),
        (pixel_format.greenshift, "G"),
        (pixel_format.blueshift, "B"),
    ):
        if shift % 8:
            raise UnsupportedPixelFormat(f"shift={shift} is not byte-aligned")
        pos = shift // 8
        pos = pos if not pixel_format.bigendian else nbytes - 1 - pos
        if pos in positions:
            raise UnsupportedPixelFormat(f"two channels share byte {pos}")
        positions[pos] = channel
    return positions


def raw_mode(pixel_format: rfb.PixelFormat) -> str:
    """The Pillow raw mode that reads bytes in this layout, ignoring depth."""
    if not pixel_format.truecolor:
        raise UnsupportedPixelFormat("colour-mapped pixel formats are not supported")

    widths = _channel_widths(pixel_format)

    if pixel_format.bpp == 32:
        if widths != (8, 8, 8):
            raise UnsupportedPixelFormat(f"32bpp channel widths {widths} unsupported")
        positions = _byte_positions(pixel_format, 4)
        mode = "".join(positions.get(i, "X") for i in range(4))
        if mode not in _32BPP_MODES:
            raise UnsupportedPixelFormat(f"32bpp layout {mode!r} has no Pillow mode")
        return mode

    if pixel_format.bpp == 24:
        if widths != (8, 8, 8):
            raise UnsupportedPixelFormat(f"24bpp channel widths {widths} unsupported")
        positions = _byte_positions(pixel_format, 3)
        mode = "".join(positions.get(i, "X") for i in range(3))
        if mode not in _24BPP_MODES:
            raise UnsupportedPixelFormat(f"24bpp layout {mode!r} has no Pillow mode")
        return mode

    if pixel_format.bpp == 16:
        if pixel_format.bigendian:
            raise UnsupportedPixelFormat("big-endian 16bpp is not supported")
        shifts = (pixel_format.redshift, pixel_format.greenshift, pixel_format.blueshift)
        # Matched as whole triples, not by asking which of red and blue sits
        # higher: the channels have unequal widths, so an arrangement that
        # passes that test can still overlap.
        try:
            # Pillow has no mirror of RGB;4B, so 444 with red in the high
            # nibble is absent here and raises.
            return {
                ((5, 6, 5), (11, 5, 0)): "BGR;16",
                ((5, 6, 5), (0, 5, 11)): "RGB;16",
                ((5, 5, 5), (10, 5, 0)): "BGR;15",
                ((5, 5, 5), (0, 5, 10)): "RGB;15",
                ((4, 4, 4), (0, 4, 8)): "RGB;4B",
            }[(widths, shifts)]
        except KeyError:
            raise UnsupportedPixelFormat(
                f"16bpp layout widths={widths} shifts={shifts} has no Pillow mode"
            ) from None

    raise UnsupportedPixelFormat(f"bpp={pixel_format.bpp} is not supported")


def _cpixel_placement(pixel_format: rfb.PixelFormat) -> str | None:
    widths = _channel_widths(pixel_format)
    shifts = (pixel_format.redshift, pixel_format.greenshift, pixel_format.blueshift)
    fits_low = all(shift + width <= 24 for shift, width in zip(shifts, widths))
    fits_high = all(shift >= 8 for shift in shifts)
    if fits_low:
        # rfbproto: when depth <= 16 both placements fit, and the low three
        # bytes are used by convention.
        return "low"
    if fits_high:
        return "high"
    return None


def cpixel_bytes(pixel_format: rfb.PixelFormat) -> int:
    """3 for a CPIXEL-eligible format, otherwise ``bypp`` (a PIXEL)."""
    if (
        pixel_format.truecolor
        and pixel_format.bpp == 32
        and pixel_format.depth <= 24
        and _cpixel_placement(pixel_format) is not None
    ):
        return 3
    return pixel_format.bypp


def cpixel_offset(pixel_format: rfb.PixelFormat) -> int:
    """Byte offset of the 3 CPIXEL bytes within a PIXEL: 0 or ``bypp - 3``.

    The placement is in value space and the offset is in byte space, so
    big-endian reverses it: the least significant three bytes of a
    big-endian pixel are the *last* three on the wire.
    """
    if cpixel_bytes(pixel_format) != 3:
        return 0
    low = _cpixel_placement(pixel_format) == "low"
    return 0 if low != pixel_format.bigendian else pixel_format.bypp - 3


PIXEL_FORMATS: dict[str, rfb.PixelFormat] = {
    "bgrx8888": rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 16, 8, 0),
    "rgbx8888": rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 0, 8, 16),
    "rgb565": rfb.PixelFormat(16, 16, False, True, 31, 63, 31, 11, 5, 0),
}
