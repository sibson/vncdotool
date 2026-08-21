"""Rect-local pixel buffer shared by decoders."""
from __future__ import annotations

from .base import DecodeError


class RectBuffer:
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
        # A decoder that fills the whole rectangle in one blit -- Raw, every
        # update -- hands over a buffer we can pass straight to the client,
        # so hold the reference instead of copying it in and back out.
        self._whole: bytes | None = None
        # The backing is reused across rectangles, so it arrives holding the
        # previous one. A write covering the whole buffer replaces all of it;
        # anything narrower has to clear it first.
        self._covered = False

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

        if x == 0 and y == 0 and w == self.width and h == self.height:
            self._whole = bytes(pixels)
            self._covered = True
            return
        self._materialize()
        self._clear()

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
        self._materialize()
        if not (x == 0 and y == 0 and w == self.width and h == self.height):
            self._clear()
        self._covered = True

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

    def _clear(self) -> None:
        if self._covered:
            return
        self._backing[:self._nbytes] = bytes(self._nbytes)
        self._covered = True

    def _materialize(self) -> None:
        """Write a held whole-rectangle blit into the backing, so a later
        partial write has something to write into."""
        if self._whole is None:
            return
        self._backing[:self._nbytes] = self._whole
        self._whole = None

    def tobytes(self) -> bytes:
        if self._whole is not None:
            return self._whole
        return bytes(self._backing[:self._nbytes])
