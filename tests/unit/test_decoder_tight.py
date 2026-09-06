"""Tight framing, assembled a rectangle at a time.

Each case states the bytes for the one rule it checks. Whole sessions a real
server sent are replayed for their pixels by test_goldens.py, against the
committed fixtures under ``fixtures/goldens/tigervnc-tight-*``.

``specs/tight-wire.md`` is the wire brief these cases check.
"""
from __future__ import annotations

import io
import random
import tracemalloc
import unittest
import zlib
from typing import Optional, Sequence, Tuple

from PIL import Image

from vncdotool.const import Encoding
from vncdotool.decoders import DecodeError
from vncdotool.decoders.tight import (
    FILL, FILTER_COPY, FILTER_GRADIENT, FILTER_PALETTE, JPEG, MIN_TO_COMPRESS, TightDecoder,
)
from vncdotool.pixelformat import PIXEL_FORMATS, TPIXEL_FORMAT, PixelFormat, tpixel_bytes

PIXEL_FORMAT = PIXEL_FORMATS["bgrx8888"]
TBYTES = tpixel_bytes(PIXEL_FORMAT)

RED = b"\xff\x00\x00"
GREEN = b"\x00\xff\x00"
BLUE = b"\x00\x00\xff"


def compact(length: int) -> bytes:
    """*length* in the wire's compact representation (specs/tight-wire.md
    section 6).
    """
    out = bytearray()
    while True:
        byte, length = length & 0x7F, length >> 7
        out.append(byte | (0x80 if length else 0))
        if not length:
            return bytes(out)


def fill(colour: bytes, reset: int = 0) -> bytes:
    return bytes([(FILL << 4) | reset]) + colour


def basic(
    payload: bytes,
    *,
    stream: int = 0,
    filter_id: Optional[int] = None,
    palette: Sequence[bytes] = (),
    reset: int = 0,
    compressor: Optional[object] = None,
) -> bytes:
    """A BasicCompression rectangle carrying *payload*, the bytes the filter
    produces: TPIXELs for the copy filter, palette indices for the palette one.

    Under MIN_TO_COMPRESS payload bytes the wire carries them raw, with no
    compact length and no zlib (specs/tight-wire.md section 6). The two
    threshold cases below assert that shape directly, so they still fail if
    the constant moves.
    """
    kind = stream | (0x04 if filter_id is not None else 0)
    wire = bytearray([(kind << 4) | reset])
    if filter_id is not None:
        wire.append(filter_id)
    if palette:
        wire.append(len(palette) - 1)
        wire += b"".join(palette)
    if len(payload) < MIN_TO_COMPRESS:
        return bytes(wire + payload)
    stream_object = compressor if compressor is not None else zlib.compressobj()
    block = stream_object.compress(payload) + stream_object.flush(zlib.Z_SYNC_FLUSH)
    return bytes(wire + compact(len(block)) + block)


def decode_rect(
    wire: bytes,
    width: int,
    height: int,
    decoder: Optional[TightDecoder] = None,
    pixel_format: PixelFormat = PIXEL_FORMAT,
) -> Tuple[bytes, PixelFormat, int]:
    """The pixels one ``decodeRect`` produced, the format they are in, and how
    many bytes it took. A framing bug shows up as the wrong count long before
    it shows up as the wrong image.
    """
    generator = (decoder or TightDecoder()).decodeRect(width, height, pixel_format)
    consumed, block = 0, None
    while True:
        try:
            size = generator.send(block)
        except StopIteration as stop:
            pixels, output_format = stop.value
            return pixels, output_format, consumed
        block = wire[consumed:consumed + size]
        if len(block) != size:
            raise AssertionError(f"decoder asked for {size} bytes at offset {consumed}, {len(block)} left")
        consumed += size


def decode(
    wire: bytes,
    width: int,
    height: int,
    decoder: Optional[TightDecoder] = None,
) -> Tuple[bytes, int]:
    pixels, _, consumed = decode_rect(wire, width, height, decoder)
    return pixels, consumed


def compact_length(data: bytes) -> int:
    generator = TightDecoder()._compactLength()
    block, offset = None, 0
    while True:
        try:
            size = generator.send(block)
        except StopIteration as stop:
            return stop.value
        block = data[offset:offset + size]
        offset += size


def pack_mono(rows: Sequence[Sequence[int]], width: int) -> bytes:
    """*rows* of palette indices, one bit per pixel MSB-first, each row padded
    out to a byte (specs/tight-wire.md section 5).
    """
    out = bytearray()
    for row in rows:
        packed = bytearray((width + 7) // 8)
        for x, index in enumerate(row):
            packed[x >> 3] |= index << (7 - (x & 7))
        out += packed
    return bytes(out)


class TestFraming(unittest.TestCase):
    """The rules that desynchronise the byte stream when read wrongly."""

    def test_a_fill_rectangle_is_a_control_byte_and_one_tpixel(self) -> None:
        pixels, consumed = decode(fill(RED), 4, 2)

        self.assertEqual(consumed, 1 + TBYTES)
        self.assertEqual(pixels, RED * 8)

    def test_the_filter_byte_is_absent_when_bit_6_is_clear(self) -> None:
        wire = basic(RED + GREEN + BLUE + RED)

        pixels, consumed = decode(wire, 4, 1)

        self.assertFalse(wire[0] & 0x40)
        self.assertEqual(consumed, len(wire))
        self.assertEqual(pixels, RED + GREEN + BLUE + RED)

    def test_the_filter_byte_follows_the_control_byte_when_bit_6_is_set(self) -> None:
        wire = basic(RED + GREEN + BLUE + RED, filter_id=FILTER_COPY)

        pixels, consumed = decode(wire, 4, 1)

        self.assertTrue(wire[0] & 0x40)
        self.assertEqual(wire[1], FILTER_COPY)
        self.assertEqual(consumed, len(wire))
        self.assertEqual(pixels, RED + GREEN + BLUE + RED)

    def test_palette_size_is_stored_minus_one(self) -> None:
        wire = basic(
            pack_mono([[0, 1, 1, 0]], 4), filter_id=FILTER_PALETTE, palette=[RED, GREEN]
        )

        pixels, _ = decode(wire, 4, 1)

        self.assertEqual(wire[2], 1, "a stored 1 is a two-colour palette")
        self.assertEqual(pixels, RED + GREEN + GREEN + RED)

    def test_a_two_colour_palette_pads_each_row_to_a_byte(self) -> None:
        rows = [[1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 1], [0, 1, 0, 0, 1, 1, 1, 1, 0, 1, 0]]
        payload = pack_mono(rows, 11)
        self.assertEqual(len(payload), 2 * 2, "11 pixels take two bytes a row, not 1.375")

        pixels, consumed = decode(
            basic(payload, filter_id=FILTER_PALETTE, palette=[RED, GREEN]), 11, 2
        )

        self.assertEqual(consumed, 1 + 1 + 1 + 2 * TBYTES + len(payload))
        self.assertEqual(pixels, b"".join([RED, GREEN][i] for row in rows for i in row))

    def test_a_palette_above_two_colours_is_one_byte_per_pixel(self) -> None:
        payload = bytes([0, 1, 2, 1])

        pixels, _ = decode(
            basic(payload, filter_id=FILTER_PALETTE, palette=[RED, GREEN, BLUE]), 4, 1
        )

        self.assertEqual(pixels, RED + GREEN + BLUE + GREEN)

    def test_eleven_filtered_bytes_arrive_raw(self) -> None:
        payload = bytes(i % 3 for i in range(11))
        wire = basic(payload, filter_id=FILTER_PALETTE, palette=[RED, GREEN, BLUE])

        pixels, consumed = decode(wire, 11, 1)

        self.assertEqual(consumed, len(wire))
        self.assertEqual(wire[-len(payload):], payload, "the payload is on the wire uncompressed")
        self.assertEqual(pixels, b"".join([RED, GREEN, BLUE][i] for i in payload))

    def test_twelve_filtered_bytes_arrive_zlib_behind_a_compact_length(self) -> None:
        payload = bytes(i % 3 for i in range(12))
        wire = basic(payload, filter_id=FILTER_PALETTE, palette=[RED, GREEN, BLUE])

        pixels, consumed = decode(wire, 12, 1)

        self.assertEqual(consumed, len(wire))
        self.assertNotIn(payload, wire, "twelve bytes are compressed, not raw")
        self.assertEqual(pixels, b"".join([RED, GREEN, BLUE][i] for i in payload))

    def test_the_third_compact_length_byte_carries_eight_bits(self) -> None:
        # 0x90 0x4E is the spec's own worked example for 10000; 4194303 is the
        # largest length three bytes can carry, the third holding 8 payload
        # bits rather than 7 (specs/tight-wire.md section 6).
        self.assertEqual(compact_length(b"\x90\x4e"), 10000)
        self.assertEqual(compact_length(b"\xff\xff\xff"), 4194303)

    def test_a_block_over_16383_bytes_needs_a_three_byte_compact_length(self) -> None:
        # Random TPIXELs, so the block stays about as long as the payload and
        # its length needs the third byte. Two bytes reach only 16383.
        payload = random.Random(0).randbytes(100 * 60 * TBYTES)
        compressor = zlib.compressobj()
        block = compressor.compress(payload) + compressor.flush(zlib.Z_SYNC_FLUSH)
        self.assertGreater(len(block), 16383)
        self.assertEqual(len(compact(len(block))), 3)

        wire = basic(payload)

        pixels, consumed = decode(wire, 100, 60)

        self.assertEqual(consumed, len(wire))
        self.assertEqual(pixels, payload)

    def test_the_four_streams_are_kept_apart(self) -> None:
        one, two = zlib.compressobj(), zlib.compressobj()
        payload = bytes(i % 3 for i in range(12))
        decoder = TightDecoder()
        palette = [RED, GREEN, BLUE]

        first, _ = decode(
            basic(payload, stream=0, filter_id=FILTER_PALETTE, palette=palette, compressor=one),
            12, 1, decoder)
        second, _ = decode(
            basic(payload, stream=1, filter_id=FILTER_PALETTE, palette=palette, compressor=two),
            12, 1, decoder)
        # Each continues its own stream, which only decodes against the
        # dictionary that stream already holds.
        third, _ = decode(
            basic(payload, stream=0, filter_id=FILTER_PALETTE, palette=palette, compressor=one),
            12, 1, decoder)

        self.assertEqual(first, second)
        self.assertEqual(first, third)


class TestStreamResets(unittest.TestCase):
    """TigerVNC never sets a reset bit, so no capture reaches these
    (specs/tight-wire.md section 2).
    """

    PAYLOAD = bytes(i % 3 for i in range(12))
    PALETTE = [RED, GREEN, BLUE]

    def _rect(self, compressor: object, reset: int = 0) -> bytes:
        return basic(
            self.PAYLOAD, stream=2, filter_id=FILTER_PALETTE, palette=self.PALETTE,
            reset=reset, compressor=compressor,
        )

    def test_a_reset_bit_restarts_that_stream(self) -> None:
        decoder, first_stream = TightDecoder(), zlib.compressobj()
        expected, _ = decode(self._rect(first_stream), 12, 1, decoder)
        decode(self._rect(first_stream), 12, 1, decoder)

        # A fresh compressor's output only decodes against a fresh stream.
        again, _ = decode(self._rect(zlib.compressobj(), reset=0x04), 12, 1, decoder)

        self.assertEqual(again, expected)

    def test_without_the_reset_bit_the_stream_keeps_its_dictionary(self) -> None:
        decoder, first_stream = TightDecoder(), zlib.compressobj()
        decode(self._rect(first_stream), 12, 1, decoder)
        decode(self._rect(first_stream), 12, 1, decoder)

        with self.assertRaises((zlib.error, DecodeError)):
            decode(self._rect(zlib.compressobj()), 12, 1, decoder)

    def test_a_fill_rectangle_honours_a_reset_bit(self) -> None:
        decoder, first_stream = TightDecoder(), zlib.compressobj()
        expected, _ = decode(self._rect(first_stream), 12, 1, decoder)
        decode(self._rect(first_stream), 12, 1, decoder)

        # Fill carries no zlib data at all, and still resets stream 2.
        decode(fill(RED, reset=0x04), 2, 2, decoder)
        again, _ = decode(self._rect(zlib.compressobj()), 12, 1, decoder)

        self.assertEqual(again, expected)


class TestRefusals(unittest.TestCase):
    def test_a_wide_fill_rectangle_is_accepted(self) -> None:
        pixels, consumed = decode(fill(RED), 3000, 1)

        self.assertEqual(consumed, 1 + TBYTES)
        self.assertEqual(len(pixels), 3000 * TBYTES)

    def test_a_wide_basic_rectangle_is_refused(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode(basic(RED * 4), 3000, 1)

        self.assertIn("2048", str(caught.exception))

    def test_the_gradient_filter_is_refused_by_name(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode(basic(RED * 4, filter_id=FILTER_GRADIENT), 4, 1)

        self.assertIn("Gradient", str(caught.exception))

    def test_jpeg_data_that_is_not_a_jfif_stream_is_refused(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode(bytes([JPEG << 4]) + compact(4) + b"\x00" * 4, 4, 1)

        self.assertIn("JPEG", str(caught.exception))

    def test_basic_without_zlib_is_refused(self) -> None:
        for control in (0xA0, 0xE0):
            with self.subTest(control=control):
                with self.assertRaises(DecodeError) as caught:
                    decode(bytes([control]) + b"\x00" * 8, 4, 1)

                self.assertIn("-317", str(caught.exception))

    def test_an_undefined_compression_type_is_refused(self) -> None:
        with self.assertRaises(DecodeError):
            decode(bytes([0xF0]) + b"\x00" * 8, 4, 1)

    def test_a_palette_index_outside_the_palette_is_refused(self) -> None:
        # Above two colours an index is a whole byte, so it can name an entry
        # the palette does not have; the two-colour rows are bits and cannot.
        wire = basic(bytes([0, 5, 1, 0]), filter_id=FILTER_PALETTE, palette=[RED, GREEN, BLUE])

        with self.assertRaises(DecodeError) as caught:
            decode(wire, 4, 1)

        self.assertIn("palette", str(caught.exception))


def jfif(image: Image.Image, quality: int = 100) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def jpeg_rect(payload: bytes, reset: int = 0) -> bytes:
    return bytes([(JPEG << 4) | reset]) + compact(len(payload)) + payload


def gradient_image(width: int, height: int) -> Image.Image:
    return Image.frombytes(
        "RGB", (width, height),
        bytes(v for y in range(height) for x in range(width)
              for v in (x * 8 % 256, y * 8 % 256, (x + y) * 4 % 256)),
    )


def offering_jpeg(decoder: Optional[TightDecoder] = None) -> TightDecoder:
    """A decoder told a quality level was offered, as a client asking for JPEG
    would leave it. Without that it refuses JPEG rectangles outright.
    """
    decoder = decoder if decoder is not None else TightDecoder()
    decoder.encodingsOffered(frozenset({Encoding(Encoding.JPEG_32 + 9)}))
    return decoder


class TestJpeg(unittest.TestCase):
    WIDTH = 16
    HEIGHT = 8

    def setUp(self) -> None:
        self.image = gradient_image(self.WIDTH, self.HEIGHT)
        self.payload = jfif(self.image)
        self.wire = jpeg_rect(self.payload)

    def test_a_compact_length_then_that_many_bytes_of_jfif(self) -> None:
        _, _, consumed = decode_rect(self.wire, self.WIDTH, self.HEIGHT, offering_jpeg())

        self.assertEqual(self.wire[0] >> 4, 0x09)
        self.assertEqual(self.payload[:2], b"\xff\xd8", "a JFIF stream opens with SOI")
        self.assertEqual(consumed, 1 + len(compact(len(self.payload))) + len(self.payload))

    def test_the_min_to_compress_rule_does_not_apply(self) -> None:
        tiny = jfif(gradient_image(1, 1))
        wire = jpeg_rect(tiny)

        _, _, consumed = decode_rect(wire, 1, 1, offering_jpeg())

        self.assertEqual(consumed, 1 + len(compact(len(tiny))) + len(tiny))

    def test_it_decodes_to_24bpp_rgb_whatever_was_negotiated(self) -> None:
        self.assertEqual(PIXEL_FORMAT.bpp, 32)

        pixels, output_format, _ = decode_rect(
            self.wire, self.WIDTH, self.HEIGHT, offering_jpeg())

        self.assertEqual(output_format, TPIXEL_FORMAT)
        self.assertEqual(len(pixels), self.WIDTH * self.HEIGHT * 3)

    def test_it_stays_24bpp_rgb_at_a_16bpp_negotiated_format(self) -> None:
        # At bgrx8888 a TPIXEL is three bytes too, so only a second format separates "JPEG is
        # always 24 bpp RGB" from a coincidence.
        pixels, output_format, _ = decode_rect(
            self.wire, self.WIDTH, self.HEIGHT, offering_jpeg(),
            pixel_format=PIXEL_FORMATS["rgb565"])

        self.assertEqual(output_format, TPIXEL_FORMAT)
        self.assertEqual(len(pixels), self.WIDTH * self.HEIGHT * 3)

    def test_it_decodes_to_the_image_it_was_encoded_from(self) -> None:
        pixels, _, _ = decode_rect(self.wire, self.WIDTH, self.HEIGHT, offering_jpeg())

        original = self.image.tobytes()
        worst = max(abs(a - b) for a, b in zip(pixels, original))
        self.assertLessEqual(worst, 8, "quality 100 should stay within a lossy bound")

    def test_a_jpeg_rectangle_honours_a_reset_bit(self) -> None:
        # Reset bits apply even to a type carrying no zlib data (specs/tight-wire.md section 2).
        payload = bytes(i % 3 for i in range(12))
        palette = [RED, GREEN, BLUE]
        decoder, stream = offering_jpeg(), zlib.compressobj()
        expected, _ = decode(
            basic(payload, stream=2, filter_id=FILTER_PALETTE, palette=palette, compressor=stream),
            12, 1, decoder)
        decode(
            basic(payload, stream=2, filter_id=FILTER_PALETTE, palette=palette, compressor=stream),
            12, 1, decoder)

        decode_rect(jpeg_rect(self.payload, reset=0x04), self.WIDTH, self.HEIGHT, decoder)
        again, _ = decode(
            basic(payload, stream=2, filter_id=FILTER_PALETTE, palette=palette,
                  compressor=zlib.compressobj()),
            12, 1, decoder)

        self.assertEqual(again, expected)

    def test_a_rectangle_whose_image_is_the_wrong_size_is_refused(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode_rect(self.wire, self.WIDTH + 1, self.HEIGHT, offering_jpeg())

        self.assertIn("JPEG", str(caught.exception))

    def test_a_header_declaring_an_implausible_size_is_refused(self) -> None:
        payload = bytearray(self.payload)
        offset = 2
        while payload[offset + 1] not in (0xC0, 0xC1, 0xC2):
            self.assertEqual(payload[offset], 0xFF, "lost the JFIF marker chain")
            offset += 2 + ((payload[offset + 2] << 8) | payload[offset + 3])
        # A start-of-frame segment is length, precision, then height and width, two bytes each.
        payload[offset + 5:offset + 9] = (65500).to_bytes(2, "big") * 2

        with self.assertRaises(DecodeError) as caught:
            decode_rect(jpeg_rect(bytes(payload)), self.WIDTH, self.HEIGHT, offering_jpeg())

        self.assertIn("JPEG", str(caught.exception))

    def test_a_one_component_jpeg_becomes_grey_rgb(self) -> None:
        # TurboVNC under -subsamp gray sends a 1-component JPEG (specs/tight-wire.md section 4).
        payload = jfif(self.image.convert("L"))
        self.assertEqual(len(Image.open(io.BytesIO(payload)).getbands()), 1)

        pixels, output_format, consumed = decode_rect(
            jpeg_rect(payload), self.WIDTH, self.HEIGHT, offering_jpeg())

        self.assertEqual(output_format, TPIXEL_FORMAT)
        self.assertEqual(len(pixels), self.WIDTH * self.HEIGHT * 3)
        triples = {pixels[i:i + 3] for i in range(0, len(pixels), 3)}
        self.assertTrue(
            all(triple[0] == triple[1] == triple[2] for triple in triples),
            "one component expanded to three must leave every pixel grey",
        )


class TestUnsolicitedJpeg(unittest.TestCase):
    """A conforming server sends JPEG only to a client that offered a quality
    level (specs/tight-wire.md section 8). One that sends it anyway would make
    a capture lossy without the user having asked for that.
    """

    WIDTH = 16
    HEIGHT = 8

    def setUp(self) -> None:
        self.wire = jpeg_rect(jfif(gradient_image(self.WIDTH, self.HEIGHT)))

    def test_it_is_refused_when_nothing_was_offered(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode_rect(self.wire, self.WIDTH, self.HEIGHT, TightDecoder())

        self.assertIn("JpegCompression", str(caught.exception))

    def test_it_is_refused_when_the_offer_held_no_quality_level(self) -> None:
        decoder = TightDecoder()
        decoder.encodingsOffered(frozenset({Encoding.TIGHT, Encoding.RAW}))

        with self.assertRaises(DecodeError) as caught:
            decode_rect(self.wire, self.WIDTH, self.HEIGHT, decoder)

        self.assertIn("JpegCompression", str(caught.exception))

    def test_any_of_the_ten_levels_allows_it(self) -> None:
        for level in range(10):
            with self.subTest(level=level):
                decoder = TightDecoder()
                decoder.encodingsOffered(
                    frozenset({Encoding(Encoding.JPEG_32 + level)}))

                _, output_format, _ = decode_rect(
                    self.wire, self.WIDTH, self.HEIGHT, decoder)

                self.assertEqual(output_format, TPIXEL_FORMAT)

    def test_a_lossless_rectangle_is_unaffected(self) -> None:
        wire = basic(RED + GREEN + BLUE + RED)

        pixels, _ = decode(wire, 4, 1)

        self.assertEqual(pixels, RED + GREEN + BLUE + RED)


class TestOversizedZlibBlock(unittest.TestCase):
    """A zlib block that inflates past the pixels its rectangle declares. No
    server sends one; unbounded, decompressing it exhausts memory before the
    size check can reject it.
    """

    WANTED = 16 * 4 * 3
    INFLATED = 64 << 20
    BUDGET = 1 << 20

    def setUp(self) -> None:
        block = zlib.compress(b"\x00" * self.INFLATED, 9)
        self.assertLess(len(block), self.BUDGET, "the declared length must stay small")
        # Control byte 0: BasicCompression, stream 0, no filter byte.
        self.wire = bytes([0x00]) + compact(len(block)) + block

    def test_it_is_refused(self) -> None:
        with self.assertRaises(DecodeError) as caught:
            decode(self.wire, 16, 4)

        self.assertIn(str(self.WANTED), str(caught.exception))

    def test_it_is_refused_without_inflating_it(self) -> None:
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            with self.assertRaises(DecodeError):
                decode(self.wire, 16, 4)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLess(
            peak, self.BUDGET,
            f"decoding a {self.WANTED}-byte rectangle peaked at {peak} bytes",
        )


if __name__ == "__main__":
    unittest.main()
