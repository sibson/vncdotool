"""The pump is designed in specs/decoder-architecture.md, under "Decoders are
generators", "One paste per rectangle" and "Errors, not hangs".
"""
from __future__ import annotations

import gzip
from pathlib import Path
from struct import pack, unpack
from unittest import TestCase, mock

from vncdotool import client, decoders, rfb
from vncdotool.const import Encoding
from vncdotool.pixelformat import TPIXEL_FORMAT

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures" / "goldens" / "tigervnc-raw-bgrx8888"
)


def make_client() -> client.VNCDoToolClient:
    cli = client.VNCDoToolClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    cli.factory.shared = 0
    cli.factory.password = None
    return cli


def pump(cli: rfb.RFBClient, decoder, x: int, y: int, width: int, height: int) -> None:
    """Dispatch one rectangle the way `_handleRectangle` would, without going
    through the registry to find the decoder.
    """
    cli._pumpRectangle(decoder, x, y, width, height)


def make_pump_client() -> rfb.RFBClient:
    """A client in the state the pump methods run in."""
    cli = rfb.RFBClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    cli._handler = cli._handleExpected
    cli.rectangles = 0
    cli.rectanglePos = []
    return cli


def raw_update(x: int, y: int, width: int, height: int, pixels: bytes) -> bytes:
    """A FramebufferUpdate holding one Raw rectangle. RFC 6143 7.6.1, 7.7.1."""
    header = pack("!BxH", 0, 1)  # msg-type, padding, number-of-rectangles
    rect_header = pack("!HHHHi", x, y, width, height, Encoding.RAW)
    return header + rect_header + pixels


class FakeWholeRect(decoders.WholeRectDecoder):
    """Fills the rectangle with one TPIXEL colour, in two reads so the pump
    has to resume the generator.
    """

    ENCODING = Encoding.TIGHT

    def decodeRect(self, width, height, pixel_format):
        colour = yield 3
        (invert,) = yield 1
        if invert:
            colour = bytes(byte ^ 0xFF for byte in colour)
        return colour * (width * height), TPIXEL_FORMAT


def whole_rect_update(*rects: tuple[int, int, int, int, bytes]) -> bytes:
    """RFC 6143 7.6.1."""
    out = pack("!BxH", 0, len(rects))
    for x, y, width, height, payload in rects:
        out += pack("!HHHHi", x, y, width, height, FakeWholeRect.ENCODING) + payload
    return out


class TestSegmentation(TestCase):
    def test_byte_at_a_time_matches_a_single_call(self) -> None:
        init = gzip.decompress((FIXTURE / "init.bin.gz").read_bytes())
        step = gzip.decompress(next(iter(sorted(FIXTURE.glob("step-*.bin.gz")))).read_bytes())

        whole = make_client()
        whole.dataReceived(init)
        whole.dataReceived(step)

        trickled = make_client()
        trickled.dataReceived(init)
        for i in range(len(step)):
            trickled.dataReceived(step[i:i + 1])

        assert whole.screen is not None
        assert trickled.screen is not None
        self.assertEqual(trickled.screen.tobytes(), whole.screen.tobytes())


class TestDecodeErrorHandling(TestCase):
    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_decode_error_reports_and_disconnects(self) -> None:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()

        def failing() -> object:
            raise decoders.DecodeError("bogus subencoding")
            yield  # pragma: no cover - never reached

        cli._pumpGenerator(None, failing(), (0, 0, 1, 1))

        cli.vncProtocolError.assert_called_once()
        self.assertIn("bogus subencoding", cli.vncProtocolError.call_args.args[0])
        cli.transport.loseConnection.assert_called_once()


class TestMultiYieldDecoders(TestCase):
    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_a_decoder_is_resumed_with_each_block_in_turn(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()
        seen = []

        class TwoStep(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                seen.append((yield 2))
                seen.append((yield 3))
                target.blit(0, 0, target.width, target.height, b"\x01" * (target.width * target.height * target.bypp))

        pump(cli, TwoStep(), 0, 0, 1, 1)
        cli.dataReceived(b"ab")
        cli.dataReceived(b"cde")

        self.assertEqual(seen, [b"ab", b"cde"])
        cli.updateRectangle.assert_called_once()

    def test_malformed_input_that_raises_from_unpack_is_diagnosed(self) -> None:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()

        class Bogus(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                block = yield 2
                unpack("!I", block)  # four bytes wanted, two yielded

        pump(cli, Bogus(), 0, 0, 1, 1)
        cli.dataReceived(b"ab")

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()


class TestAbort(TestCase):
    """Driven through `dataReceived` rather than by calling the pump: the
    parked handler is only re-entered by `_handleExpected`'s loop, so a
    direct call cannot see a failure that forgot to disarm it.
    """

    def setUp(self) -> None:
        self.cli = make_pump_client()

    def _failing_client(self) -> rfb.RFBClient:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()
        cli.commitUpdate = mock.Mock()

        class Failing(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                yield 2
                raise decoders.DecodeError("boom")

        pump(cli, Failing(), 0, 0, 2, 1)
        return cli

    def test_nothing_is_painted_after_a_failed_decode(self) -> None:
        cli = self._failing_client()

        cli.dataReceived(b"ab" + b"CDEFGHIJKLMNOP")

        cli.vncProtocolError.assert_called_once()
        cli.updateRectangle.assert_not_called()
        cli.commitUpdate.assert_not_called()

    def test_bytes_arriving_after_a_failed_decode_are_discarded(self) -> None:
        cli = self._failing_client()
        cli.dataReceived(b"ab")

        cli.dataReceived(b"more bytes the server had already sent")

        cli.updateRectangle.assert_not_called()
        self.assertEqual(cli.vncProtocolError.call_count, 1)

    def test_a_decoder_asking_for_a_negative_count_is_refused(self) -> None:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()

        class Backwards(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                yield -8

        pump(cli, Backwards(), 0, 0, 1, 1)

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()


class TestRectBufferValidation(TestCase):
    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_a_rectangle_larger_than_the_framebuffer_is_refused(self) -> None:
        cli = self.cli
        cli.width, cli.height = 64, 48

        with self.assertRaises(decoders.DecodeError):
            cli.rectBuffer(65, 10)

    def test_the_pump_turns_that_refusal_into_a_disconnect(self) -> None:
        """`rectBuffer` raises inside the decoder's generator, which is the
        pump's to catch: a decoder never sees it.
        """
        cli = self.cli
        cli.width, cli.height = 64, 48
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        class Ordinary(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                yield target.width * target.height * target.bypp

        pump(cli, Ordinary(), 0, 0, 65, 10)

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()

    def test_a_zero_dimension_rectangle_is_not_an_error(self) -> None:
        cli = self.cli

        self.assertIsNotNone(cli.rectBuffer(0, 10))
        self.assertIsNotNone(cli.rectBuffer(10, 0))

    def test_the_largest_allowed_rectangle_is_accepted(self) -> None:
        """The refusals above pass just as well against an off-by-one that
        rejects everything.
        """
        self.assertIsNotNone(self.cli.rectBuffer(self.cli.MAX_DESKTOP_SIZE, 1))


class TestCopyRectPump(TestCase):
    """CopyRect is a `ClientDecoder`: it reads its source off the wire and
    blits framebuffer-to-framebuffer, never through `updateRectangle`.
    """

    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_copyRectangle_called_with_wire_source_and_no_paint(self) -> None:
        cli = self.cli
        cli.width, cli.height = 64, 48
        cli.copyRectangle = mock.Mock()
        cli.updateRectangle = mock.Mock()
        decoder = cli._decoders[Encoding.COPY_RECTANGLE]

        pump(cli, decoder, 5, 6, 10, 20)
        cli.dataReceived(pack("!HH", 1, 2))  # srcx, srcy

        cli.copyRectangle.assert_called_once_with(1, 2, 5, 6, 10, 20)
        cli.updateRectangle.assert_not_called()

    def test_a_copy_from_outside_the_framebuffer_is_refused(self) -> None:
        cli = self.cli
        cli.width, cli.height = 64, 48
        cli.copyRectangle = mock.Mock()
        cli.vncProtocolError = mock.Mock()

        decoder = cli._decoders[Encoding.COPY_RECTANGLE]
        pump(cli, decoder, 0, 0, 10, 10)
        cli.dataReceived(pack("!HH", 60, 0))

        cli.copyRectangle.assert_not_called()
        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()


class TestOnePastePerRectangle(TestCase):
    """One `updateRectangle` call per rectangle, carrying the negotiated
    `PixelFormat` -- not called until the whole rectangle has arrived.
    """

    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_single_call_with_negotiated_pixel_format(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()
        decoder = cli._decoders[Encoding.RAW]
        width, height = 4, 3
        pixels = bytes(range(width * height * cli.bypp))

        pump(cli, decoder, 0, 0, width, height)
        cli.dataReceived(pixels[:5])
        cli.updateRectangle.assert_not_called()
        cli.dataReceived(pixels[5:])

        cli.updateRectangle.assert_called_once_with(
            0, 0, width, height, pixels, cli.pixel_format
        )

    def test_the_rectangle_lands_where_the_wire_said(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()
        decoder = cli._decoders[Encoding.RAW]
        pixels = bytes(range(2 * 2 * cli.bypp))

        pump(cli, decoder, 7, 9, 2, 2)
        cli.dataReceived(pixels)

        cli.updateRectangle.assert_called_once_with(7, 9, 2, 2, pixels, cli.pixel_format)


class TestRectBufferReuse(TestCase):
    """A smaller rectangle after a larger one reads back only its own bytes.

    Two blits per rectangle, because a single whole-rectangle blit never
    reaches the shared backing (`decoders/buffer.py`).
    """

    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_smaller_rectangle_after_larger_gets_only_its_own_bytes(self) -> None:
        cli = self.cli

        big = cli.rectBuffer(4, 4)
        half = bytes([0xFF]) * (4 * 2 * cli.bypp)
        big.blit(0, 0, 4, 2, half)
        big.blit(0, 2, 4, 2, half)
        self.assertEqual(big.tobytes(), bytes([0xFF]) * (4 * 4 * cli.bypp))

        small = cli.rectBuffer(2, 2)
        row = bytes([0xAA]) * (2 * 1 * cli.bypp)
        small.blit(0, 0, 2, 1, row)
        small.blit(0, 1, 2, 1, row)

        expected = bytes([0xAA]) * (2 * 2 * cli.bypp)
        self.assertEqual(small.tobytes(), expected)
        self.assertEqual(len(small.tobytes()), 2 * 2 * cli.bypp)


class TestDecodersThatSkipTheBuffer(TestCase):
    """Raw hands the pump its wire bytes rather than filling a buffer; an
    ordinary `PixelDecoder` still gets one allocated for it.
    """

    def test_a_buffered_decoder_still_decodes(self) -> None:
        cli = make_pump_client()
        cli.updateRectangle = mock.Mock()

        class Ordinary(decoders.PixelDecoder):
            def decodePixels(self, target, pixel_format):
                data = yield target.width * target.height * target.bypp
                target.blit(0, 0, target.width, target.height, data)

        pixels = bytes(range(2 * 2 * cli.bypp))
        pump(cli, Ordinary(), 0, 0, 2, 2)
        cli.dataReceived(pixels)

        cli.updateRectangle.assert_called_once_with(
            0, 0, 2, 2, pixels, cli.pixel_format
        )
        self.assertNotEqual(cli._rect_backing, bytearray())

    def test_raw_allocates_no_buffer(self) -> None:
        """Nothing in the pump knows Raw skips the buffer, so nothing but
        this holds the shortcut in place.
        """
        cli = make_pump_client()
        cli.updateRectangle = mock.Mock()

        pixels = bytes(range(2 * 2 * cli.bypp))
        pump(cli, cli._decoders[Encoding.RAW], 0, 0, 2, 2)
        cli.dataReceived(pixels)

        cli.updateRectangle.assert_called_once_with(
            0, 0, 2, 2, pixels, cli.pixel_format
        )
        self.assertEqual(cli._rect_backing, bytearray())

    def test_a_rectangle_larger_than_the_framebuffer_is_refused(self) -> None:
        """Raw computes its byte count from the rectangle header, so it has
        to bound the dimensions itself rather than inheriting the check
        `rectBuffer` makes.
        """
        cli = make_pump_client()
        cli.width, cli.height = 64, 48
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        decoder = cli._decoders[Encoding.RAW]
        pump(cli, decoder, 0, 0, 65, 10)

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()


class TestWholeRectPump(TestCase):
    def setUp(self) -> None:
        self.cli = make_pump_client()

    def test_the_rectangle_carries_the_decoders_format_not_the_negotiated_one(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()

        pump(cli, FakeWholeRect(), 3, 4, 2, 2)
        cli.dataReceived(b"\x10\x20\x30\x00")

        cli.updateRectangle.assert_called_once_with(
            3, 4, 2, 2, b"\x10\x20\x30" * 4, TPIXEL_FORMAT
        )
        self.assertNotEqual(TPIXEL_FORMAT.bypp, cli.pixel_format.bypp)

    def test_no_buffer_is_allocated(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()

        pump(cli, FakeWholeRect(), 0, 0, 8, 8)
        cli.dataReceived(b"\x10\x20\x30\x00")

        cli.updateRectangle.assert_called_once()
        self.assertEqual(cli._rect_backing, bytearray())

    def test_nothing_is_painted_until_the_rectangle_is_complete(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()

        pump(cli, FakeWholeRect(), 0, 0, 2, 2)
        cli.dataReceived(b"\x10\x20\x30")

        cli.updateRectangle.assert_not_called()

        cli.dataReceived(b"\x01")

        cli.updateRectangle.assert_called_once_with(
            0, 0, 2, 2, b"\xef\xdf\xcf" * 4, TPIXEL_FORMAT
        )

    def test_the_rectangle_is_recorded_and_the_update_continues(self) -> None:
        cli = self.cli
        cli.updateRectangle = mock.Mock()
        cli.commitUpdate = mock.Mock()

        pump(cli, FakeWholeRect(), 3, 4, 2, 2)
        cli.dataReceived(b"\x10\x20\x30\x00")

        self.assertEqual(cli.rectanglePos, [(3, 4, 2, 2)])
        cli.commitUpdate.assert_called_once_with([(3, 4, 2, 2)])

    def test_a_rectangle_larger_than_the_framebuffer_is_refused(self) -> None:
        cli = self.cli
        cli.width, cli.height = 64, 48
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        pump(cli, FakeWholeRect(), 0, 0, 65, 10)

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()

    def test_a_decode_error_aborts_rather_than_propagating(self) -> None:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        class Failing(decoders.WholeRectDecoder):
            def decodeRect(self, width, height, pixel_format):
                yield 3
                raise decoders.DecodeError("unknown compression control byte")

        pump(cli, Failing(), 0, 0, 2, 2)
        cli.dataReceived(b"\x10\x20\x30")

        cli.vncProtocolError.assert_called_once()
        self.assertIn(
            "unknown compression control byte", cli.vncProtocolError.call_args.args[0]
        )
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()


class TestWholeRectLength(TestCase):
    """Neither a buffer nor a byte count off the wire bounds this path, so
    the pump measures what the decoder handed back.
    """

    def _abort_for(self, produced: bytes) -> rfb.RFBClient:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        class WrongLength(decoders.WholeRectDecoder):
            def decodeRect(self, width, height, pixel_format):
                yield 1
                return produced, TPIXEL_FORMAT

        pump(cli, WrongLength(), 0, 0, 2, 2)
        cli.dataReceived(b"\x00")
        return cli

    def test_too_few_bytes_is_refused(self) -> None:
        cli = self._abort_for(bytes(2 * 2 * TPIXEL_FORMAT.bypp - 1))

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()

    def test_a_refused_rectangle_is_not_recorded_as_a_screen_change(self) -> None:
        cli = self._abort_for(bytes(2 * 2 * TPIXEL_FORMAT.bypp - 1))

        self.assertEqual(cli.rectanglePos, [])

    def test_pixels_without_a_format_are_refused(self) -> None:
        """The pump cannot size them, and recording the rectangle without
        painting it would lose the update rather than report it.
        """
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        class Formatless(decoders.PixelDecoder):
            def decode(self, client, rect, pixel_format):
                data = yield 4
                return decoders.Outcome(True, data, None)

        pump(cli, Formatless(), 0, 0, 2, 2)
        cli.dataReceived(b"\x00\x00\x00\x00")

        cli.vncProtocolError.assert_called_once()
        cli.updateRectangle.assert_not_called()
        self.assertEqual(cli.rectanglePos, [])

    def test_too_many_bytes_is_refused(self) -> None:
        cli = self._abort_for(bytes(2 * 2 * TPIXEL_FORMAT.bypp + 1))

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()

    def test_the_exact_length_is_accepted(self) -> None:
        """The refusals above pass just as well against a check that
        rejects everything.
        """
        cli = self._abort_for(bytes(2 * 2 * TPIXEL_FORMAT.bypp))

        cli.vncProtocolError.assert_not_called()
        cli.updateRectangle.assert_called_once()


class TestWholeRectSegmentation(TestCase):
    """`TestSegmentation` proves this against a captured Raw stream, which
    yields once per rectangle. A decoder that yields several times has more
    ways to mis-handle a split, so prove it against one of those too.
    """

    def _client(self) -> client.VNCDoToolClient:
        cli = make_client()
        decoder = FakeWholeRect()
        cli._decoders[FakeWholeRect.ENCODING] = decoder
        cli.dataReceived(gzip.decompress((FIXTURE / "init.bin.gz").read_bytes()))
        return cli

    def test_byte_at_a_time_matches_a_single_call(self) -> None:
        update = whole_rect_update(
            (0, 0, 4, 3, b"\xde\xad\xbe\x00"),
            (8, 5, 2, 2, b"\x01\x02\x03\x01"),
        )

        whole = self._client()
        whole.dataReceived(update)

        trickled = self._client()
        for i in range(len(update)):
            trickled.dataReceived(update[i:i + 1])

        assert whole.screen is not None
        assert trickled.screen is not None
        self.assertEqual(
            whole.screen.convert("RGB").getpixel((0, 0)), (0xDE, 0xAD, 0xBE)
        )
        self.assertEqual(trickled.screen.tobytes(), whole.screen.tobytes())
