"""Rect-local pixel buffer shared by decoders."""
from __future__ import annotations

from .base import DecodeError


class RectBuffer:
    """A rect-sized, rect-local pixel buffer that decoders fill."""

    def __init__(self, width: int, height: int, bypp: int, backing: bytearray | None = None) -> None:
        self.width = width
        self.height = height
        self.bypp = bypp
        needed = width * height * bypp
        if backing is None:
            backing = bytearray(needed)
        elif len(backing) < needed:
            raise ValueError(f"backing too small: need {needed} bytes, got {len(backing)}")
        self._backing = backing
        self._nbytes = needed

    def _check_rect(self, x: int, y: int, w: int, h: int) -> None:
        if x < 0 or y < 0 or w < 0 or h < 0:
            raise DecodeError(f"negative rect: x={x}, y={y}, w={w}, h={h}")
        if x + w > self.width or y + h > self.height:
            raise DecodeError(
                f"rect ({x}, {y}, {w}, {h}) extends past buffer bounds "
                f"({self.width}x{self.height})"
            )

    def blit(self, x: int, y: int, w: int, h: int, pixels: bytes) -> None:
        self._check_rect(x, y, w, h)
        expected = w * h * self.bypp
        if len(pixels) != expected:
            raise DecodeError(f"blit expected {expected} bytes, got {len(pixels)}")

        stride = self.width * self.bypp
        row_bytes = w * self.bypp
        buf = self._backing

        if x == 0 and w == self.width:
            # Contiguous rows: one slice assignment instead of h separate copies.
            offset = y * stride
            buf[offset:offset + expected] = pixels
            return

        x_off = x * self.bypp
        for row in range(h):
            dst = (y + row) * stride + x_off
            src = row * row_bytes
            buf[dst:dst + row_bytes] = pixels[src:src + row_bytes]

    def fill(self, x: int, y: int, w: int, h: int, color: bytes) -> None:
        self._check_rect(x, y, w, h)
        if len(color) != self.bypp:
            raise DecodeError(f"fill color must be {self.bypp} bytes, got {len(color)}")

        stride = self.width * self.bypp
        row_bytes = w * self.bypp
        row = color * w
        buf = self._backing

        if x == 0 and w == self.width:
            offset = y * stride
            buf[offset:offset + h * stride] = row * h
            return

        x_off = x * self.bypp
        for r in range(h):
            dst = (y + r) * stride + x_off
            buf[dst:dst + row_bytes] = row

    def tobytes(self) -> bytes:
        return bytes(self._backing[:self._nbytes])
