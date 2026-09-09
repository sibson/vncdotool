"""Imports nothing, so the scene player can run this arithmetic inside the
fleet images. tests/.dockerignore keeps `goldens/scenes.py` out of those
images, and the player has to place a cell exactly where the tests outside
expect it.
"""
from typing import Optional, Tuple

SCREEN = (256, 192)
KEYS = ("0", "c", "d", "f", "g", "p", "s", "x")
COLUMNS = 4
ROWS = (len(KEYS) + COLUMNS - 1) // COLUMNS
CELL = (SCREEN[0] // COLUMNS, SCREEN[1] // ROWS)


def click_target(key: str) -> Tuple[int, int]:
    index = KEYS.index(key)
    column, row = index % COLUMNS, index // COLUMNS
    return column * CELL[0] + CELL[0] // 2, row * CELL[1] + CELL[1] // 2


def scene_at(x: int, y: int) -> Optional[str]:
    column, row = x // CELL[0], y // CELL[1]
    if not 0 <= column < COLUMNS:
        return None
    index = row * COLUMNS + column
    return KEYS[index] if 0 <= index < len(KEYS) else None
