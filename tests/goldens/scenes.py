"""Screen content for golden capture, as pure functions of the prior screen.

Committed to PNGs by this module's own main(), played back by
scene_player.py and used directly by distillation and the unit suite -- it
must import nothing X-specific.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageStat

OUT_DIR = Path(__file__).resolve().parent / "scenes"

SIZE = (256, 192)

# A capture archive keeps the two stream directions apart, so a distilled
# step learns which key produced it only from this patch inside the frame.
# Centred in whatever it is stamped on, so the label survives a server
# serving a geometry these scenes were not drawn for.
PATCH_SIZE = 48
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


def _centre(image: Image.Image) -> tuple:
    width, height = image.size
    return width // 2, height // 2


def stamp_patch(image: Image.Image, key: str) -> None:
    x, y = _centre(image)
    half = PATCH_SIZE // 2
    colour = (ord(key), _PATCH_GREEN, _PATCH_BLUE)
    box = [max(x - half, 0), max(y - half, 0), min(x + half - 1, image.size[0] - 1), min(y + half - 1, image.size[1] - 1)]
    ImageDraw.Draw(image).rectangle(box, fill=colour)


def patch_candidates(image: Image.Image, tolerance: Tuple[int, int, int] = (0, 0, 0)) -> List[str]:
    """Which scenes this frame's centre patch could belong to.

    ``stamp_patch`` draws a square into the middle of each scene image
    coloured ``(ord(key), _PATCH_GREEN, _PATCH_BLUE)``, so the scene's
    identity reaches the client as ordinary pixels and is quantized with
    them. Scene keys sit one unit apart in red, and rgb565 keeps five bits
    of it, which puts ``c``, ``d``, ``f`` and ``g`` on one value -- so at a
    reduced depth the patch names a set of scenes rather than one.
    """
    red, green, blue = image.convert("RGB").getpixel(_centre(image))
    red_bound, green_bound, blue_bound = tolerance
    if abs(green - _PATCH_GREEN) > green_bound or abs(blue - _PATCH_BLUE) > blue_bound:
        return []
    return [key for key in SCENES if abs(red - ord(key)) <= red_bound]


def _nearest_scene(image: Image.Image, candidates: List[str]) -> str:
    """Which of several candidate scenes the frame most resembles.

    A ranking, never a threshold: "lands within the format's quantization of
    its scene" is the golden test's own claim, and a fixture labelled by it
    could never fail that test.

    Only reachable because the patch carries the scene as a colour, which a
    reduced depth can collapse. Stamping the key's glyph instead would name
    the scene outright at any format and retire this.
    """
    frame = image.convert("RGB")

    def distance(key: str) -> float:
        scene = Image.open(OUT_DIR / f"{key}.png").convert("RGB")
        return sum(ImageStat.Stat(ImageChops.difference(frame, scene)).sum)

    return min(candidates, key=distance)


def read_patch(image: Image.Image, tolerance: Tuple[int, int, int] = (0, 0, 0)) -> Optional[str]:
    candidates = patch_candidates(image, tolerance)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return _nearest_scene(image, candidates)


def apply(key: str, screen: Image.Image) -> Image.Image:
    image = SCENES[key](screen)
    stamp_patch(image, key)
    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    screen = base()
    for key in SCENES:
        screen = apply(key, screen)
        screen.save(OUT_DIR / f"{key}.png")
    print(f"wrote {len(SCENES)} scenes to {OUT_DIR}")


if __name__ == "__main__":
    main()
