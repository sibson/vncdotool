"""Screen content for golden capture, as pure functions of the prior screen.

Committed to PNGs by this module's own main(), played back by
scene_player.py and used directly by distillation and the unit suite -- it
must import nothing X-specific.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent / "scenes"

SIZE = (256, 192)

# A capture archive keeps the two stream directions apart, so a distilled
# step learns which key produced it only from this patch inside the frame.
# Centred in whatever it is stamped on, so the label survives a server
# serving a geometry these scenes were not drawn for.
#
# Black and white are every channel's extremes, and a pixel format reproduces
# its extremes exactly however few bits it keeps: 0 stays 0 and the maximum
# comes back as 255. A patch drawn in the two of them reaches the client
# unquantized at rgb565 as much as at rgbx8888.
GLYPH_INK = (0, 0, 0)
GLYPH_PAPER = (255, 255, 255)
GLYPH_SIZE = (5, 7)
GLYPH_CELL = 4
GLYPH_MARGIN = 3
PATCH_SIZE = (
    GLYPH_SIZE[0] * GLYPH_CELL + 2 * GLYPH_MARGIN,
    GLYPH_SIZE[1] * GLYPH_CELL + 2 * GLYPH_MARGIN,
)

# Uppercase forms of the lowercase scene keys: at 5x7 the lowercase set needs
# descenders for g and p, and the rest turns to mush. 0 keeps a slash so it
# cannot be read as D.
GLYPHS: Dict[str, Tuple[str, ...]] = {
    "0": (
        " ### ",
        "#   #",
        "#  ##",
        "# # #",
        "##  #",
        "#   #",
        " ### ",
    ),
    "s": (
        " ### ",
        "#   #",
        "#    ",
        " ### ",
        "    #",
        "#   #",
        " ### ",
    ),
    "d": (
        "###  ",
        "#  # ",
        "#   #",
        "#   #",
        "#   #",
        "#  # ",
        "###  ",
    ),
    "x": (
        "#   #",
        "#   #",
        " # # ",
        "  #  ",
        " # # ",
        "#   #",
        "#   #",
    ),
    "g": (
        " ### ",
        "#   #",
        "#    ",
        "# ###",
        "#   #",
        "#   #",
        " ### ",
    ),
    "p": (
        "#### ",
        "#   #",
        "#   #",
        "#### ",
        "#    ",
        "#    ",
        "#    ",
    ),
    "c": (
        " ### ",
        "#   #",
        "#    ",
        "#    ",
        "#    ",
        "#   #",
        " ### ",
    ),
    "f": (
        "#####",
        "#    ",
        "#    ",
        "#### ",
        "#    ",
        "#    ",
        "#    ",
    ),
}

_KEY_BY_GLYPH: Dict[Tuple[str, ...], str] = {glyph: key for key, glyph in GLYPHS.items()}
_INK_THRESHOLD = 3 * 128


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


def _glyph_origin(image: Image.Image) -> Tuple[int, int]:
    x, y = _centre(image)
    columns, rows = GLYPH_SIZE
    return x - columns * GLYPH_CELL // 2, y - rows * GLYPH_CELL // 2


def stamp_patch(image: Image.Image, key: str) -> None:
    width, height = PATCH_SIZE
    if image.size[0] < width or image.size[1] < height:
        raise ValueError(f"a {width}x{height} patch does not fit a {image.size[0]}x{image.size[1]} screen")

    x, y = _centre(image)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [x - width // 2, y - height // 2, x - width // 2 + width - 1, y - height // 2 + height - 1],
        fill=GLYPH_PAPER,
    )
    left, top = _glyph_origin(image)
    for row, line in enumerate(GLYPHS[key]):
        for column, cell in enumerate(line):
            if cell == "#":
                cell_left, cell_top = left + column * GLYPH_CELL, top + row * GLYPH_CELL
                draw.rectangle(
                    [cell_left, cell_top, cell_left + GLYPH_CELL - 1, cell_top + GLYPH_CELL - 1],
                    fill=GLYPH_INK,
                )


def read_patch(image: Image.Image) -> Optional[str]:
    """Which scene this frame's centre patch names, or None if it names none.

    One sample per glyph cell, thresholded and matched against the table
    whole. Nothing here is a tolerance: ink and paper survive every pixel
    format exactly, so a frame either carries a glyph or does not.
    """
    if image.size[0] < PATCH_SIZE[0] or image.size[1] < PATCH_SIZE[1]:
        return None

    frame = image.convert("RGB")
    left, top = _glyph_origin(image)
    columns, rows = GLYPH_SIZE

    def cell(column: int, row: int) -> str:
        pixel = frame.getpixel((
            left + column * GLYPH_CELL + GLYPH_CELL // 2,
            top + row * GLYPH_CELL + GLYPH_CELL // 2,
        ))
        return "#" if sum(pixel) < _INK_THRESHOLD else " "

    read = tuple("".join(cell(column, row) for column in range(columns)) for row in range(rows))
    return _KEY_BY_GLYPH.get(read)


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
