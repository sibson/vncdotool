"""What every decoder is: an error, three shapes, and the rectangle they fill.

specs/decoder-architecture.md is the design.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from ..rfb import PixelFormat
    from .buffer import RectBuffer


class DecodeError(Exception):
    """Malformed, oversized or unsupported encoded data."""


@runtime_checkable
class PixelDecoder(Protocol):
    """Consumes bytes, fills a rect buffer."""

    def decode(self, target: "RectBuffer", pixel_format: "PixelFormat") -> Iterator[int]:
        ...

    def output_format(self, pixel_format: "PixelFormat") -> "PixelFormat":
        """The layout the bytes this decoder wrote are in.

        The negotiated format for every encoding in use today; Tight's JPEG
        and TPIXEL will differ.
        """


@runtime_checkable
class ClientDecoder(Protocol):
    """Consumes bytes, calls a client method.

    CopyRect needs the screen rather than a rect buffer, and Cursor produces
    an image and a mask rather than a rectangle.
    """

    def decode(
        self, client: object, rect: tuple[int, int, int, int], pixel_format: "PixelFormat"
    ) -> Iterator[int]:
        ...


@runtime_checkable
class ControlDecoder(Protocol):
    """Consumes nothing, changes client state."""

    def apply(self, client: object, rect: tuple[int, int, int, int]) -> None:
        ...
