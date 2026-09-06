"""How near two screenshots have to be to count as the same screen.

Shared by `VNCDoToolClient.expectScreen` and the golden replay suite, which
have to agree on what a match is.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageFilter, ImageMath, ImageStat

from . import pixelformat

# Kotsarenko & Ramos (2010), by way of pixelmatch: perceived difference in
# YIQ, weighted towards luma because that is where the eye resolves detail
# and where a lossy encoder spends least of its error.
_Y = (0.29889531, 0.58662247, 0.11448223)
_I = (0.59597799, -0.27417610, -0.32180189)
_Q = (0.11147015, -0.52248202, 0.41101187)
_WEIGHTS = (0.5053, 0.299, 0.1957)

# The largest delta the formula can produce for two 8-bit pixels, which puts
# every score on a 0..255 scale whatever the pixel format underneath.
MAX_DELTA = 35215.0


def _bands(image: Image.Image) -> tuple[Image.Image, Image.Image, Image.Image]:
    red, green, blue = (band.convert("F") for band in image.convert("RGB").split())
    return tuple(  # type: ignore[return-value]
        ImageMath.unsafe_eval(
            "cr*r + cg*g + cb*b", r=red, g=green, b=blue, cr=cr, cg=cg, cb=cb
        )
        for cr, cg, cb in (_Y, _I, _Q)
    )


def _delta_for(differences: tuple[float, float, float]) -> float:
    """The score for a pixel that differs by this much in Y, I and Q."""
    return sum(weight * value**2 for weight, value in zip(_WEIGHTS, differences))


def _scale(delta: float) -> float:
    return 255.0 * math.sqrt(delta / MAX_DELTA)


def _blurred(image: Image.Image, blur: int) -> Image.Image:
    if not blur:
        return image
    return image.convert("RGB").filter(ImageFilter.BoxBlur(blur))


def worst_delta(actual: Image.Image, expected: Image.Image, blur: int = 0) -> float:
    """The furthest any one pixel sits from its counterpart, 0..255.

    Kept as a float: rounding it to a channel value would put a screen that
    differs in one blue bit at zero, and `expect FILE 0` has to mean exact.
    """
    left, right = _blurred(actual, blur), _blurred(expected, blur)
    y1, i1, q1 = _bands(left)
    y2, i2, q2 = _bands(right)
    scored = ImageMath.unsafe_eval(
        "255.0 * ((wy*(y1-y2)**2 + wi*(i1-i2)**2 + wq*(q1-q2)**2) / m) ** 0.5",
        y1=y1, i1=i1, q1=q1, y2=y2, i2=i2, q2=q2, m=MAX_DELTA,
        wy=_WEIGHTS[0], wi=_WEIGHTS[1], wq=_WEIGHTS[2],
    )
    _lowest, highest = scored.getextrema()
    return highest


def bound_for_channels(channels: tuple[int, int, int]) -> int:
    """The worst score a per-channel error of this size can add up to.

    Signs are free -- a server may round any channel either way -- so each
    coefficient contributes its magnitude.
    """
    return math.ceil(
        _scale(
            _delta_for(
                tuple(  # type: ignore[arg-type]
                    sum(abs(coefficient) * channel for coefficient, channel in zip(axis, channels))
                    for axis in (_Y, _I, _Q)
                )
            )
        )
    )


def fuzz_for_format(pixel_format: pixelformat.PixelFormat) -> int:
    """What a screen may differ by when the format alone accounts for it."""
    return bound_for_channels(pixelformat.channel_tolerance(pixel_format))


def matches(actual: Image.Image, expected: Image.Image, fuzz: int, blur: int = 0) -> bool:
    """Whether every pixel of `actual` is within `fuzz` of `expected`."""
    if actual.size != expected.size:
        return False
    worst = ImageStat.Stat(
        ImageChops.difference(actual.convert("RGB"), expected.convert("RGB"))
    ).extrema
    channels = tuple(high for _low, high in worst)
    # A box blur averages, so no pixel can come out further apart than the
    # furthest pair going in: an RGB bound taken before the blur still holds
    # after it.
    if bound_for_channels(channels) <= fuzz:  # type: ignore[arg-type]
        return True
    return worst_delta(actual, expected, blur) <= fuzz
