import itertools
from typing import Iterator
from unittest import TestCase

from PIL import Image

from vncdotool import rfb
from vncdotool.pixelformat import UnsupportedPixelFormat, cpixel_bytes, cpixel_offset, raw_mode

BGRX8888 = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 16, 8, 0)
BGRX8888_DEPTH32 = rfb.PixelFormat(32, 32, False, True, 255, 255, 255, 16, 8, 0)
BGRX8888_BIGENDIAN = rfb.PixelFormat(32, 24, True, True, 255, 255, 255, 16, 8, 0)
RGBX8888 = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 0, 8, 16)
XRGB8888 = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 8, 16, 24)
XBGR8888 = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 24, 16, 8)

RGB24 = rfb.PixelFormat(24, 24, False, True, 255, 255, 255, 0, 8, 16)
BGR24 = rfb.PixelFormat(24, 24, False, True, 255, 255, 255, 16, 8, 0)

BGR565 = rfb.PixelFormat(16, 16, False, True, 31, 63, 31, 11, 5, 0)
RGB565 = rfb.PixelFormat(16, 16, False, True, 31, 63, 31, 0, 5, 11)
BGR555 = rfb.PixelFormat(16, 15, False, True, 31, 31, 31, 10, 5, 0)
RGB555 = rfb.PixelFormat(16, 15, False, True, 31, 31, 31, 0, 5, 10)
RGB444 = rfb.PixelFormat(16, 12, False, True, 15, 15, 15, 0, 4, 8)


def every_layout() -> Iterator[rfb.PixelFormat]:
    """Every channel arrangement of the widths a server may negotiate.

    Both endiannesses throughout, including the arrangements that have no
    Pillow mode: what they must do is raise, and a generated case cannot be
    forgotten the way a listed one can.
    """
    for bpp, depth, maxima, slots in (
        (32, 24, (255, 255, 255), (0, 8, 16, 24)),
        (24, 24, (255, 255, 255), (0, 8, 16)),
        (16, 16, (31, 63, 31), (0, 5, 11)),
        (16, 15, (31, 31, 31), (0, 5, 10)),
        (16, 12, (15, 15, 15), (0, 4, 8)),
    ):
        for shifts in itertools.permutations(slots, 3):
            for bigendian in (False, True):
                yield rfb.PixelFormat(bpp, depth, bigendian, True, *maxima, *shifts)


def every_colour(maxima: tuple[int, int, int]) -> Iterator[tuple[int, int, int]]:
    """Primaries, black, white, and a mid value per channel.

    Mid values are what separate a correct shift from one that happens to
    look right at full intensity, where every bit of the channel is set.
    """
    yield (0, 0, 0)
    yield maxima
    for channel, maximum in enumerate(maxima):
        for value in (maximum, maximum // 2, 1):
            intensities = [0, 0, 0]
            intensities[channel] = value
            yield tuple(intensities)  # type: ignore[misc]


def pack(pixel_format: rfb.PixelFormat, red: int, green: int, blue: int) -> bytes:
    """Encode (red, green, blue) as PIXEL bytes for pixel_format's own layout."""
    value = (
        (red << pixel_format.redshift)
        | (green << pixel_format.greenshift)
        | (blue << pixel_format.blueshift)
    )
    return value.to_bytes(pixel_format.bpp // 8, "big" if pixel_format.bigendian else "little")


class TestRawMode(TestCase):

    def test_resolves_every_format_pillow_can_read(self):
        """raw_mode picks the Pillow mode string for each covered layout."""
        cases = {
            BGRX8888: "BGRX",
            RGBX8888: "RGBX",
            XRGB8888: "XRGB",
            XBGR8888: "XBGR",
            RGB24: "RGB",
            BGR24: "BGR",
            BGR565: "BGR;16",
            RGB565: "RGB;16",
            BGR555: "BGR;15",
            RGB555: "RGB;15",
            RGB444: "RGB;4B",
        }
        for pixel_format, expected in cases.items():
            with self.subTest(pixel_format=pixel_format):
                self.assertEqual(raw_mode(pixel_format), expected)

    def test_depth_does_not_affect_the_resolved_mode(self):
        """The depth-32 declaration libvncserver-example sends resolves the same."""
        self.assertEqual(raw_mode(BGRX8888), raw_mode(BGRX8888_DEPTH32))

    def test_endianness_changes_the_resolved_mode(self):
        """Byte order, unlike depth, does change which mode applies."""
        self.assertNotEqual(raw_mode(BGRX8888), raw_mode(BGRX8888_BIGENDIAN))
        self.assertEqual(raw_mode(BGRX8888_BIGENDIAN), "XRGB")

    def test_every_layout_either_decodes_correctly_or_is_refused(self):
        """Over every channel arrangement, not the handful we thought to list.

        A mode that resolves must decode the primaries it claims to; a layout
        Pillow cannot read must raise. There is no third outcome, and in
        particular no silently wrong mode.
        """
        resolved = set()

        for pixel_format in every_layout():
            with self.subTest(pixel_format=pixel_format):
                try:
                    mode = raw_mode(pixel_format)
                except UnsupportedPixelFormat:
                    continue
                resolved.add(mode)
                maxima = (pixel_format.redmax, pixel_format.greenmax, pixel_format.bluemax)
                for intensities in every_colour(maxima):
                    data = pack(pixel_format, *intensities)
                    decoded = Image.frombytes("RGB", (1, 1), data, "raw", mode).getpixel((0, 0))
                    for channel, (value, maximum) in enumerate(zip(intensities, maxima)):
                        # Pillow scales an n-bit channel to 8 bits by its own
                        # rounding, so this bounds the result rather than
                        # restating the rounding and passing by construction.
                        self.assertAlmostEqual(decoded[channel], value * 255 / maximum, delta=1)

        self.assertEqual(
            resolved,
            {"RGBX", "BGRX", "XRGB", "XBGR", "RGB", "BGR", "BGR;16", "RGB;16", "BGR;15", "RGB;15", "RGB;4B"},
        )

    def test_rgb565_is_red_in_the_high_bits(self):
        """0x00F8 little-endian through BGR;16 is pure red."""
        self.assertEqual(raw_mode(BGR565), "BGR;16")
        image = Image.frombytes("RGB", (1, 1), bytes([0x00, 0xF8]), "raw", "BGR;16")
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_colour_mapped_is_unsupported(self):
        pixel_format = rfb.PixelFormat(8, 8, False, False, 0, 0, 0, 0, 0, 0)
        with self.assertRaises(UnsupportedPixelFormat):
            raw_mode(pixel_format)

    def test_bigendian_16bpp_is_unsupported(self):
        pixel_format = rfb.PixelFormat(16, 16, True, True, 31, 63, 31, 11, 5, 0)
        with self.assertRaises(UnsupportedPixelFormat):
            raw_mode(pixel_format)

    def test_channel_widths_outside_the_covered_set_are_unsupported(self):
        """10-bit channels: a real deep-colour layout Pillow has no mode for."""
        pixel_format = rfb.PixelFormat(32, 30, False, True, 1023, 1023, 1023, 20, 10, 0)
        with self.assertRaises(UnsupportedPixelFormat):
            raw_mode(pixel_format)

    def test_non_byte_aligned_32bpp_shifts_are_unsupported(self):
        pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 4, 12, 20)
        with self.assertRaises(UnsupportedPixelFormat):
            raw_mode(pixel_format)


class TestCPixel(TestCase):

    def test_low_placement(self):
        """bgrx8888's colour bits fit the low three bytes."""
        self.assertEqual(cpixel_bytes(BGRX8888), 3)
        self.assertEqual(cpixel_offset(BGRX8888), 0)

    def test_high_placement(self):
        """A pad byte in position 0 pushes the colour bits into the high three."""
        pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 24, 16, 8)
        self.assertEqual(cpixel_bytes(pixel_format), 3)
        self.assertEqual(cpixel_offset(pixel_format), pixel_format.bypp - 3)

    def test_depth_16_tie_break_prefers_low(self):
        """rfbproto's corner case: depth <= 16 lets both placements fit."""
        pixel_format = rfb.PixelFormat(32, 16, False, True, 31, 63, 31, 19, 13, 8)
        self.assertEqual(cpixel_bytes(pixel_format), 3)
        self.assertEqual(cpixel_offset(pixel_format), 0)

    def test_placement_is_value_space_offset_is_byte_space(self):
        """Big-endian reverses which end of the pixel the three bytes sit at."""
        low = rfb.PixelFormat(32, 24, True, True, 255, 255, 255, 16, 8, 0)
        high = rfb.PixelFormat(32, 24, True, True, 255, 255, 255, 24, 16, 8)

        self.assertEqual(cpixel_offset(low), low.bypp - 3)
        self.assertEqual(cpixel_offset(high), 0)

    def test_the_three_bytes_carry_every_colour_bit(self):
        """Whatever is outside the reported window is pad, over every layout."""
        eligible = 0

        for pixel_format in every_layout():
            if cpixel_bytes(pixel_format) != 3:
                continue
            eligible += 1
            with self.subTest(pixel_format=pixel_format):
                pixel = pack(
                    pixel_format,
                    pixel_format.redmax,
                    pixel_format.greenmax,
                    pixel_format.bluemax,
                )
                offset = cpixel_offset(pixel_format)

                outside = pixel[:offset] + pixel[offset + 3:]

                self.assertEqual(outside, bytes(len(outside)))

        self.assertTrue(eligible)

    def test_16bpp_is_never_a_cpixel(self):
        self.assertEqual(cpixel_bytes(BGR565), BGR565.bypp)
        self.assertEqual(cpixel_offset(BGR565), 0)

    def test_depth_32_is_never_a_cpixel(self):
        pixel_format = rfb.PixelFormat(32, 32, False, True, 255, 255, 255, 0, 8, 16)
        self.assertEqual(cpixel_bytes(pixel_format), pixel_format.bypp)
        self.assertEqual(cpixel_offset(pixel_format), 0)

    def test_colour_bits_straddling_the_middle_fall_back_to_pixel_width(self):
        pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 4, 12, 20)
        self.assertEqual(cpixel_bytes(pixel_format), pixel_format.bypp)
        self.assertEqual(cpixel_offset(pixel_format), 0)
