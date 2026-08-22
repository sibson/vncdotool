"""specs/decoder-architecture.md is the design."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Iterator

from ..const import Encoding

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from ..rfb import PixelFormat
    from .buffer import RectBuffer


class DecodeError(Exception):
    """Malformed, oversized or unsupported encoded data."""


class Decoder:
    """One encoding, in one of three shapes: a subclass overrides the one
    method its shape names, and the pump calls that method alone.
    """

    # The encoding-type this decoder reads, RFC 6143 section 7.6.1.
    ENCODING: ClassVar[Encoding]

    def decodePixels(
        self, target: "RectBuffer", pixel_format: "PixelFormat"
    ) -> Iterator[int]:
        raise NotImplementedError

    def decodeForClient(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: "PixelFormat"
    ) -> Iterator[int]:
        raise NotImplementedError

    def applyToClient(self, client: object, rect: tuple[int, int, int, int]) -> None:
        raise NotImplementedError


class PixelDecoder(Decoder):
    """Consumes bytes, fills a rect buffer."""

    def output_format(self, pixel_format: "PixelFormat") -> "PixelFormat":
        """The layout the bytes this decoder wrote are in, which is not
        always the negotiated one.
        """
        return pixel_format


class ClientDecoder(Decoder):
    """Consumes bytes, calls a client method."""


class ControlDecoder(Decoder):
    """Consumes nothing, changes client state."""
