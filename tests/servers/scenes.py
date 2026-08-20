"""Screen content for golden capture, as pure functions of the prior screen.

Runs both inside the fleet containers (via scene_app.py) and offline in the
unit suite, so it must import nothing X-specific.
"""
from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from PIL import Image, ImageDraw

SIZE = (256, 192)

# A capture archive keeps the two stream directions apart, so a distilled
# step learns which key produced it only from this patch inside the frame.
PATCH_ORIGIN = (0, 0)
PATCH_SIZE = 8
_PATCH_GREEN = 0x5A
_PATCH_BLUE = 0xA5


def _seeded(key: str) -> random.Random:
    return random.Random(f"vncdotool-scene-{key}")


def base() -> Image.Image:
    image = Image.new("RGB", SIZE, (24, 24, 32))
    draw = ImageDraw.Draw(image)
    width, height = SIZE
    draw.rectangle([16, 16, width - 17, height - 17], outline=(200, 200, 40), width=2)
    draw.line([0, 0, width - 1, height - 1], fill=(180, 40, 40), width=1)
    draw.line([0, height - 1, width - 1, 0], fill=(40, 180, 60), width=1)
    return image


def _reset(screen: Image.Image) -> Image.Image:
    return base()


def _solid(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    ImageDraw.Draw(image).rectangle([32, 32, 223, 159], fill=(0, 96, 192))
    return image


def _dense(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    rng = _seeded("d")
    noise = Image.new("RGB", (192, 128))
    noise.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(192 * 128)])
    image.paste(noise, (32, 32))
    return image


def _scattered(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    draw = ImageDraw.Draw(image)
    rng = _seeded("x")
    for _ in range(64):
        x = rng.randrange(SIZE[0] - 8)
        y = rng.randrange(SIZE[1] - 8)
        draw.rectangle([x, y, x + 5, y + 5], fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    return image


def _gradient(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    width, height = SIZE
    gradient = Image.new("RGB", (width, height))
    gradient.putdata(
        [
            (x * 255 // (width - 1), y * 255 // (height - 1), 255 - (x * 255 // (width - 1)))
            for y in range(height)
            for x in range(width)
        ]
    )
    image.paste(gradient, (0, 0))
    return image


def _palette(screen: Image.Image) -> Image.Image:
    image = screen.copy()
    draw = ImageDraw.Draw(image)
    two = [(0, 0, 0), (255, 255, 255)]
    four = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    sixteen = [(v * 17, (15 - v) * 17, (v * 7) % 256) for v in range(16)]
    for band, colours in enumerate((two, four, sixteen)):
        top = 16 + band * 56
        for index, colour in enumerate(colours):
            step = 224 // len(colours)
            left = 16 + index * step
            draw.rectangle([left, top, left + step - 1, top + 47], fill=colour)
    return image


def _scroll(screen: Image.Image) -> Image.Image:
    """Scrolling is what makes a server emit CopyRect at all."""
    image = screen.copy()
    region = image.crop((0, 32, SIZE[0], SIZE[1]))
    image.paste(region, (0, 16))
    return image


def _full(screen: Image.Image) -> Image.Image:
    rng = _seeded("f")
    return Image.new("RGB", SIZE, (rng.randrange(64, 256), rng.randrange(64, 256), rng.randrange(64, 256)))


SCENES: Dict[str, Callable[[Image.Image], Image.Image]] = {
    "0": _reset,
    "s": _solid,
    "d": _dense,
    "x": _scattered,
    "g": _gradient,
    "p": _palette,
    "c": _scroll,
    "f": _full,
}


def stamp_patch(image: Image.Image, key: str) -> None:
    left, top = PATCH_ORIGIN
    colour = (ord(key), _PATCH_GREEN, _PATCH_BLUE)
    ImageDraw.Draw(image).rectangle([left, top, left + PATCH_SIZE - 1, top + PATCH_SIZE - 1], fill=colour)


def read_patch(image: Image.Image) -> Optional[str]:
    left, top = PATCH_ORIGIN
    red, green, blue = image.convert("RGB").getpixel((left + PATCH_SIZE // 2, top + PATCH_SIZE // 2))
    if (green, blue) != (_PATCH_GREEN, _PATCH_BLUE):
        return None
    key = chr(red)
    return key if key in SCENES else None


def apply(key: str, screen: Image.Image) -> Image.Image:
    image = SCENES[key](screen)
    stamp_patch(image, key)
    return image
