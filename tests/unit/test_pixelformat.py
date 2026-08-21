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

    def test_known_bytes_decode_to_known_pixels(self):
        """Each resolved mode is a correct claim about Pillow's own decoding."""
        formats = [
            BGRX8888,
            RGBX8888,
            XRGB8888,
            XBGR8888,
            BGRX8888_BIGENDIAN,
            RGB24,
            BGR24,
            BGR565,
            RGB565,
            BGR555,
            RGB555,
            RGB444,
        ]
        for pixel_format in formats:
            mode = raw_mode(pixel_format)
            with self.subTest(pixel_format=pixel_format, mode=mode):
                red = pack(pixel_format, pixel_format.redmax, 0, 0)
                green = pack(pixel_format, 0, pixel_format.greenmax, 0)
                blue = pack(pixel_format, 0, 0, pixel_format.bluemax)
                red_pixel = Image.frombytes("RGB", (1, 1), red, "raw", mode).getpixel((0, 0))
                green_pixel = Image.frombytes("RGB", (1, 1), green, "raw", mode).getpixel((0, 0))
                blue_pixel = Image.frombytes("RGB", (1, 1), blue, "raw", mode).getpixel((0, 0))
                self.assertEqual(red_pixel, (255, 0, 0))
                self.assertEqual(green_pixel, (0, 255, 0))
                self.assertEqual(blue_pixel, (0, 0, 255))

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
        """Slicing at the reported offset must not take the pad byte."""
        for pixel_format in (BGRX8888, XBGR8888, BGRX8888_BIGENDIAN):
            with self.subTest(pixel_format=pixel_format):
                order = "big" if pixel_format.bigendian else "little"
                value = (
                    0xFF << pixel_format.redshift
                    | 0x80 << pixel_format.greenshift
                    | 0x40 << pixel_format.blueshift
                )
                pixel = value.to_bytes(pixel_format.bypp, order)
                offset = cpixel_offset(pixel_format)

                cpixel = pixel[offset:offset + cpixel_bytes(pixel_format)]

                self.assertEqual(sorted(cpixel), [0x40, 0x80, 0xFF])

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
