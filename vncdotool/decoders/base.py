"""specs/decoder-architecture.md is the design."""
from __future__ import annotations

from typing import ClassVar, Iterator

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


class PixelDecoder(Decoder):
    """Consumes bytes, fills a rect buffer."""

    def output_format(self, pixel_format: PixelFormat) -> PixelFormat:
        """The layout the bytes this decoder wrote are in, which is not
        always the negotiated one.
        """
        return pixel_format


class ClientDecoder(Decoder):
    """Consumes bytes, calls a client method."""
