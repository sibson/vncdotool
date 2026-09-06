"""specs/decoder-architecture.md is the design."""
from __future__ import annotations

from typing import Any, ClassVar, Generator, Iterator, NamedTuple, Optional, Tuple

from ..const import Encoding
from ..pixelformat import PixelFormat
from .buffer import RectBuffer

Rect = Tuple[int, int, int, int]


class Outcome(NamedTuple):
    """What one rectangle did, for the pump to act on: whether it counts as a
    screen change, and any pixels the pump is left to paste.
    """

    changed: bool
    # Both or neither: pixels the pump cannot size are a rectangle silently
    # lost, so there are no defaults to write one field without the other.
    pixels: Optional[bytes]
    pixel_format: Optional[PixelFormat]


# Nothing reached the framebuffer, and the rectangle is not a screen change.
NOTHING = Outcome(False, None, None)

# The decoder changed the framebuffer itself; the pump has nothing to paste.
CHANGED = Outcome(True, None, None)


def painted(pixels: bytes, pixel_format: PixelFormat) -> Outcome:
    """A rectangle for the pump to paste, in the format the decoder wrote it
    in, which is not always the negotiated one.
    """
    return Outcome(True, pixels, pixel_format)


class Decoder:
    """One encoding: a subclass overrides the one method its base class names,
    and `decode` -- which that base class implements -- is the only entry
    point the pump calls.
    """

    # The encoding-type this decoder reads, RFC 6143 section 7.6.1.
    ENCODING: ClassVar[Encoding]

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        """Yield the byte counts this rectangle needs, each satisfied in full,
        and return what the pump is to do with the result.
        """
        raise NotImplementedError

    def decodePixels(
        self, target: RectBuffer, pixel_format: PixelFormat
    ) -> Iterator[int]:
        raise NotImplementedError

    def decodeForClient(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Iterator[int]:
        raise NotImplementedError

    def decodeRect(
        self, width: int, height: int, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Tuple[bytes, PixelFormat]]:
        raise NotImplementedError

    def decodeForControl(self, client: Any, width: int, height: int) -> None:
        raise NotImplementedError


class PixelDecoder(Decoder):
    """Consumes bytes, fills a rect buffer the pump allocates and pastes --
    unless, like Raw, it overrides `decode` to hand its own bytes over.
    """

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        target = client.rectBuffer(rect[2], rect[3])
        yield from self.decodePixels(target, pixel_format)
        return painted(target.tobytes(), self.output_format(pixel_format))

    def output_format(self, pixel_format: PixelFormat) -> PixelFormat:
        """The layout the bytes this decoder wrote are in, which is not
        always the negotiated one.
        """
        return pixel_format


class WholeRectDecoder(Decoder):
    """Consumes bytes, produces the whole rectangle itself, in whatever
    pixel format it decoded them to -- not always the negotiated one.
    """

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        client.requireFits(rect[2], rect[3])
        pixels, output_format = yield from self.decodeRect(
            rect[2], rect[3], pixel_format
        )
        return painted(pixels, output_format)


class ClientDecoder(Decoder):
    """Consumes bytes, changes the framebuffer through a client method."""

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        yield from self.decodeForClient(client, rect, pixel_format)
        return CHANGED


class ControlDecoder(Decoder):
    """Calls a client method as a side effect; its rectangle is never
    recorded as a screen change."""

    def decode(
        self, client: Any, rect: Rect, pixel_format: PixelFormat
    ) -> Generator[int, bytes, Outcome]:
        yield from ()  # consumes no bytes, so there is nothing to yield for
        self.decodeForControl(client, rect[2], rect[3])
        return NOTHING
