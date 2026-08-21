import unittest

from vncdotool.decoders.base import DecodeError
from vncdotool.decoders.buffer import RectBuffer


class TestRectBuffer(unittest.TestCase):
    def test_full_rect_blit(self):
        buf = RectBuffer(2, 2, 1)
        pixels = b"\x01\x02\x03\x04"
        buf.blit(0, 0, 2, 2, pixels)
        self.assertEqual(buf.tobytes(), pixels)

    def test_sub_rect_blit_lands_at_stride_offset(self):
        # bypp=2 makes a stride mistake (e.g. using w instead of width*bypp)
        # produce a visibly wrong offset rather than a coincidentally right one.
        buf = RectBuffer(3, 3, 2)
        buf.blit(1, 1, 1, 1, b"\xaa\xbb")
        expected = b"\x00" * 8 + b"\xaa\xbb" + b"\x00" * 8
        self.assertEqual(buf.tobytes(), expected)

    def test_sub_rect_blit_multirow(self):
        buf = RectBuffer(3, 3, 1)
        # 2x2 block at (1, 0): rows "AB" / "CD"
        buf.blit(1, 0, 2, 2, b"ABCD")
        expected = b"\x00AB\x00CD\x00\x00\x00"
        self.assertEqual(buf.tobytes(), expected)

    def test_fill(self):
        buf = RectBuffer(2, 3, 1)
        buf.fill(0, 1, 2, 1, b"\x09")
        expected = b"\x00\x00\x09\x09\x00\x00"
        self.assertEqual(buf.tobytes(), expected)

    def test_fill_sub_rect(self):
        buf = RectBuffer(3, 2, 1)
        buf.fill(1, 0, 2, 1, b"\x07")
        expected = b"\x00\x07\x07\x00\x00\x00"
        self.assertEqual(buf.tobytes(), expected)

    def test_backing_is_reused(self):
        backing = bytearray(4)
        buf = RectBuffer(2, 2, 1, backing=backing)
        # Partial, because a blit covering the whole rectangle is handed
        # straight to the client and never reaches the array.
        buf.blit(0, 0, 1, 2, b"\x01\x02")
        self.assertEqual(backing, b"\x01\x00\x02\x00")

    def test_oversized_backing_leftover_bytes_excluded(self):
        backing = bytearray(16)
        RectBuffer(4, 4, 1, backing=backing).fill(0, 0, 4, 4, b"\xaa")

        small = RectBuffer(2, 2, 1, backing=backing)
        small.fill(0, 0, 2, 2, b"\x01")

        self.assertEqual(small.tobytes(), b"\x01" * 4)
        # the previous rectangle's tail is still sitting in the backing array,
        # past what this smaller rectangle claims -- tobytes() must not leak it.
        self.assertEqual(bytes(backing), b"\x01" * 4 + b"\xaa" * 12)

    def test_backing_too_small_raises_value_error(self):
        with self.assertRaises(ValueError):
            RectBuffer(2, 2, 1, backing=bytearray(3))

    def test_blit_negative_x_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(-1, 0, 1, 1, b"\x01")

    def test_blit_negative_y_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(0, -1, 1, 1, b"\x01")

    def test_blit_negative_w_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(0, 0, -1, 1, b"")

    def test_blit_negative_h_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(0, 0, 1, -1, b"")

    def test_blit_past_right_edge_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(1, 0, 2, 1, b"\x01\x02")

    def test_blit_past_bottom_edge_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(0, 1, 1, 2, b"\x01\x02")

    def test_blit_wrong_length_pixels_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.blit(0, 0, 2, 2, b"\x01\x02\x03")

    def test_fill_negative_rect_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.fill(0, 0, -1, 1, b"\x01")

    def test_fill_past_edge_raises_decode_error(self):
        buf = RectBuffer(2, 2, 1)
        with self.assertRaises(DecodeError):
            buf.fill(1, 1, 2, 2, b"\x01")

    def test_fill_wrong_length_color_raises_decode_error(self):
        buf = RectBuffer(2, 2, 2)
        with self.assertRaises(DecodeError):
            buf.fill(0, 0, 1, 1, b"\x01")


if __name__ == "__main__":
    unittest.main()
