#!/usr/bin/env python3
"""Write the committed scene PNGs scene_app.py plays back. Manual, run once
per change to scenes.py: `uv run python -m tests.goldens.make_scenes`.
"""
from __future__ import annotations

from pathlib import Path

from tests.goldens import scenes

OUT_DIR = Path(__file__).resolve().parent / "scenes"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    screen = scenes.base()
    for key in scenes.SCENES:
        screen = scenes.apply(key, screen)
        screen.save(OUT_DIR / f"{key}.png")
    print(f"wrote {len(scenes.SCENES)} scenes to {OUT_DIR}")


if __name__ == "__main__":
    main()
