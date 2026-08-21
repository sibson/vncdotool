"""The pump: `_decodeRectangle`, `_rectBuffer`, `_pumpDecoder`, `_finishRectangle`.

No reactor, no transport, no server -- protocol classes driven directly with
a mocked Twisted transport. specs/decoder-architecture.md sections "Decoders
are generators", "One paste per rectangle", "Errors, not hangs", and R6.
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


def make_pump_client() -> rfb.RFBClient:
    """A client in the state `_decodeRectangle` runs in."""
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
    """The pump satisfies every yielded count in full, so a decoder never
    sees a partial buffer.
    """

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
    """R6: a decoder that cannot make sense of its input is a diagnosed
    disconnect, not a hang.
    """

    def test_decode_error_reports_and_disconnects(self) -> None:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        def failing() -> object:
            raise decoders.DecodeError("bogus subencoding")
            yield  # pragma: no cover - never reached

        cli._pumpDecoder(None, failing(), None)

        cli.vncProtocolError.assert_called_once()
        self.assertIn("bogus subencoding", cli.vncProtocolError.call_args.args[0])
        cli.transport.loseConnection.assert_called_once()


class TestControlDecoders(TestCase):
    """The third shape: consumes no bytes, changes client state, and must
    still hand the rectangle loop back.
    """

    def test_a_control_decoder_applies_and_the_loop_continues(self) -> None:
        cli = make_pump_client()
        cli._doConnection = mock.Mock()
        applied = []

        class Control:
            def apply(self, client: object, rect: tuple) -> None:
                applied.append(rect)

        cli._decodeRectangle(Control(), 1, 2, 3, 4)

        self.assertEqual(applied, [(1, 2, 3, 4)])
        cli._doConnection.assert_called_once()


class TestMultiYieldDecoders(TestCase):
    """Raw and CopyRect each yield once, so nothing else exercises resuming
    a generator that is still mid-decode.
    """

    def test_a_decoder_is_resumed_with_each_block_in_turn(self) -> None:
        cli = make_pump_client()
        cli.updateRectangle = mock.Mock()
        seen = []

        class TwoStep:
            def decode(self, target, pixel_format):
                seen.append((yield 2))
                seen.append((yield 3))
                target.blit(0, 0, target.width, target.height, b"\x01" * (target.width * target.height * target.bypp))

            def output_format(self, pixel_format):
                return pixel_format

        cli._decodeRectangle(TwoStep(), 0, 0, 1, 1)
        cli.dataReceived(b"ab")
        cli.dataReceived(b"cde")

        self.assertEqual(seen, [b"ab", b"cde"])
        cli.updateRectangle.assert_called_once()

    def test_malformed_input_that_raises_from_unpack_is_diagnosed(self) -> None:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        class Bogus:
            def decode(self, target, pixel_format):
                block = yield 2
                unpack("!I", block)  # four bytes wanted, two yielded

            def output_format(self, pixel_format):
                return pixel_format

        cli._decodeRectangle(Bogus(), 0, 0, 1, 1)
        cli.dataReceived(b"ab")

        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()


class TestRectBufferValidation(TestCase):
    """A rectangle outside `MAX_DESKTOP_SIZE`, or with a zero dimension, is
    refused before any buffer is allocated.
    """

    def test_oversized_rectangle_is_refused(self) -> None:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        result = cli._rectBuffer(cli.MAX_DESKTOP_SIZE + 1, 10)

        self.assertIsNone(result)
        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()

    def test_zero_width_rectangle_is_refused(self) -> None:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        result = cli._rectBuffer(0, 10)

        self.assertIsNone(result)
        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()

    def test_the_largest_allowed_rectangle_is_accepted(self) -> None:
        """The refusals above pass just as well against an off-by-one that
        rejects everything.
        """
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        self.assertIsNotNone(cli._rectBuffer(cli.MAX_DESKTOP_SIZE, 1))

        cli.vncProtocolError.assert_not_called()

    def test_zero_height_rectangle_is_refused(self) -> None:
        cli = make_pump_client()
        cli.vncProtocolError = mock.Mock()

        result = cli._rectBuffer(10, 0)

        self.assertIsNone(result)
        cli.vncProtocolError.assert_called_once()
        cli.transport.loseConnection.assert_called_once()


class TestCopyRectPump(TestCase):
    """CopyRect is a `ClientDecoder`: it reads its source off the wire and
    blits framebuffer-to-framebuffer, never through `updateRectangle`.
    """

    def test_copyRectangle_called_with_wire_source_and_no_paint(self) -> None:
        cli = make_pump_client()
        cli.copyRectangle = mock.Mock()
        cli.updateRectangle = mock.Mock()
        decoder = decoders.DECODERS[Encoding.COPY_RECTANGLE]

        cli._decodeRectangle(decoder, 5, 6, 10, 20)
        cli.dataReceived(pack("!HH", 1, 2))  # srcx, srcy

        cli.copyRectangle.assert_called_once_with(1, 2, 5, 6, 10, 20)
        cli.updateRectangle.assert_not_called()


class TestOnePastePerRectangle(TestCase):
    """One `updateRectangle` call per rectangle, carrying the negotiated
    `PixelFormat` -- not called until the whole rectangle has arrived.
    """

    def test_single_call_with_negotiated_pixel_format(self) -> None:
        cli = make_pump_client()
        cli.updateRectangle = mock.Mock()
        decoder = decoders.DECODERS[Encoding.RAW]
        width, height = 4, 3
        pixels = bytes(range(width * height * cli.bypp))

        cli._decodeRectangle(decoder, 0, 0, width, height)
        cli.dataReceived(pixels[:5])
        cli.updateRectangle.assert_not_called()
        cli.dataReceived(pixels[5:])

        cli.updateRectangle.assert_called_once_with(
            0, 0, width, height, pixels, cli.pixel_format
        )

    def test_the_rectangle_lands_where_the_wire_said(self) -> None:
        cli = make_pump_client()
        cli.updateRectangle = mock.Mock()
        decoder = decoders.DECODERS[Encoding.RAW]
        pixels = bytes(range(2 * 2 * cli.bypp))

        cli._decodeRectangle(decoder, 7, 9, 2, 2)
        cli.dataReceived(pixels)

        cli.updateRectangle.assert_called_once_with(7, 9, 2, 2, pixels, cli.pixel_format)


class TestRectBufferReuse(TestCase):
    """A smaller rectangle after a larger one reads back only its own bytes.

    Two blits per rectangle, because a single whole-rectangle blit never
    reaches the shared backing (`decoders/buffer.py`).
    """

    def test_smaller_rectangle_after_larger_gets_only_its_own_bytes(self) -> None:
        cli = make_pump_client()

        big = cli._rectBuffer(4, 4)
        half = bytes([0xFF]) * (4 * 2 * cli.bypp)
        big.blit(0, 0, 4, 2, half)
        big.blit(0, 2, 4, 2, half)
        self.assertEqual(big.tobytes(), bytes([0xFF]) * (4 * 4 * cli.bypp))

        small = cli._rectBuffer(2, 2)
        row = bytes([0xAA]) * (2 * 1 * cli.bypp)
        small.blit(0, 0, 2, 1, row)
        small.blit(0, 1, 2, 1, row)

        expected = bytes([0xAA]) * (2 * 2 * cli.bypp)
        self.assertEqual(small.tobytes(), expected)
        self.assertEqual(len(small.tobytes()), 2 * 2 * cli.bypp)
