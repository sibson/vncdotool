"""specs/decoder-architecture.md is the design."""
from __future__ import annotations

from typing import ClassVar, Generator, Iterator

from ..const import Encoding
from ..pixelformat import PixelFormat
from .buffer import RectBuffer


class Decoder:
    """One encoding: a subclass overrides the one method its base class names,
    and the pump calls that method alone.
    """

    # The encoding-type this decoder reads, RFC 6143 section 7.6.1.
    ENCODING: ClassVar[Encoding]

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        raise NotImplementedError

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: PixelFormat
    ) -> Iterator[int]:
        raise NotImplementedError


class RectDecoder(Decoder):
    """Its rectangle is a real screen change, recorded as one."""


class PixelDecoder(RectDecoder):
    """Consumes bytes, fills a rect buffer."""

    # False when the decoder's wire bytes are already its output bytes, in order.
    buffered: ClassVar[bool] = True

    def output_format(self, pixel_format: PixelFormat) -> PixelFormat:
        """The layout the bytes this decoder wrote are in, which is not
        always the negotiated one.
        """
        return pixel_format


class WholeRectDecoder(RectDecoder):
    """Consumes bytes, produces the whole rectangle itself.

    The format it returns need not be the negotiated one: Tight's TPIXEL is
    three bytes where the negotiated format is four (rfbproto, Tight
    Encoding).
    """

    def decodeRect(
        self, width: int, height: int, pixel_format: PixelFormat
    ) -> Generator[int, bytes, tuple[bytes, PixelFormat]]:
        raise NotImplementedError


class ClientDecoder(RectDecoder):
    """Consumes bytes, calls a client method."""


class ControlDecoder(Decoder):
    """Calls a client method as a side effect; its rectangle is never
    recorded as a screen change."""

    def decodeForControl(self, client: object, width: int, height: int) -> None:
        """Unlike decodePixels/decodeForClient, not a generator: this
        consumes no bytes, so there is nothing to yield for.
        """
        raise NotImplementedError
