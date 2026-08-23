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
    """Dispatch one rectangle the way `_handleRectangle` would, without the
    registry: the client pairs a decoder with a pump method at connect time.
    """
    cli._pumpFor(decoder)(decoder, x, y, width, height)


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

        cli._pumpBlock(None, failing(), None)

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
        cli.vncProtocolError = mock.Mock()

        result = cli._allocateRectBuffer(65, 10)

        self.assertIsNone(result)
        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()

    def test_a_zero_dimension_rectangle_is_not_an_error(self) -> None:
        cli = self.cli
        cli.vncProtocolError = mock.Mock()

        self.assertIsNotNone(cli._allocateRectBuffer(0, 10))
        self.assertIsNotNone(cli._allocateRectBuffer(10, 0))

        cli.vncProtocolError.assert_not_called()

    def test_the_largest_allowed_rectangle_is_accepted(self) -> None:
        """The refusals above pass just as well against an off-by-one that
        rejects everything.
        """
        cli = self.cli
        cli.vncProtocolError = mock.Mock()

        self.assertIsNotNone(cli._allocateRectBuffer(cli.MAX_DESKTOP_SIZE, 1))

        cli.vncProtocolError.assert_not_called()


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
        decoder, _ = cli._decoders[Encoding.COPY_RECTANGLE]

        pump(cli, decoder, 5, 6, 10, 20)
        cli.dataReceived(pack("!HH", 1, 2))  # srcx, srcy

        cli.copyRectangle.assert_called_once_with(1, 2, 5, 6, 10, 20)
        cli.updateRectangle.assert_not_called()

    def test_a_copy_from_outside_the_framebuffer_is_refused(self) -> None:
        cli = self.cli
        cli.width, cli.height = 64, 48
        cli.copyRectangle = mock.Mock()
        cli.vncProtocolError = mock.Mock()

        decoder, _ = cli._decoders[Encoding.COPY_RECTANGLE]
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
        decoder, _ = cli._decoders[Encoding.RAW]
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
        decoder, _ = cli._decoders[Encoding.RAW]
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

        big = cli._allocateRectBuffer(4, 4)
        half = bytes([0xFF]) * (4 * 2 * cli.bypp)
        big.blit(0, 0, 4, 2, half)
        big.blit(0, 2, 4, 2, half)
        self.assertEqual(big.tobytes(), bytes([0xFF]) * (4 * 4 * cli.bypp))

        small = cli._allocateRectBuffer(2, 2)
        row = bytes([0xAA]) * (2 * 1 * cli.bypp)
        small.blit(0, 0, 2, 1, row)
        small.blit(0, 1, 2, 1, row)

        expected = bytes([0xAA]) * (2 * 2 * cli.bypp)
        self.assertEqual(small.tobytes(), expected)
        self.assertEqual(len(small.tobytes()), 2 * 2 * cli.bypp)


class TestWholeRectangleDecoders(TestCase):
    """A decoder whose whole output is one contiguous run of pixels skips the
    buffer; one that says nothing keeps the generator path.
    """

    def test_a_decoder_that_declares_nothing_still_decodes(self) -> None:
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

    def test_a_rectangle_larger_than_the_framebuffer_is_refused(self) -> None:
        """The fast path reads its byte count from the rectangle header, so
        it has to bound the dimensions itself rather than inheriting the
        check `_allocateRectBuffer` makes.
        """
        cli = make_pump_client()
        cli.width, cli.height = 64, 48
        cli.vncProtocolError = mock.Mock()
        cli.updateRectangle = mock.Mock()

        decoder, _ = cli._decoders[Encoding.RAW]
        pump(cli, decoder, 0, 0, 65, 10)

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()
        cli.updateRectangle.assert_not_called()
