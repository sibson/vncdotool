#!/usr/bin/env python3
"""Fullscreen X client that blits a committed scene PNG per keypress."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image
from Xlib import X, display

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.goldens import click_targets  # noqa: E402

DEFAULT_SCENE_DIR = Path(__file__).resolve().parent / "scenes"
# Keeps each PutImage request under the server's maximum request length.
BAND_ROWS = 32


def _to_zpixmap(image: Image.Image) -> bytes:
    """Depth-24 ZPixmap data: B, G, R, pad per pixel on an LSBFirst server."""
    return image.convert("RGB").tobytes("raw", "BGRX")


class ScenePlayer:
    def __init__(self, scene_dir: Path) -> None:
        self.scene_dir = scene_dir
        self.display = display.Display()
        if self.display.display.info.image_byte_order != 0:
            raise SystemExit("scene_player: X server is not LSBFirst; ZPixmap byte order would be wrong")
        screen = self.display.screen()
        self.screen_image = Image.open(self.scene_dir / "0.png")
        width, height = self.screen_image.size
        self.window = screen.root.create_window(
            0, 0, width, height, 0, screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=screen.black_pixel,
            override_redirect=True,
            event_mask=X.ExposureMask | X.ButtonPressMask,
        )
        # Without this, key and button events never reach the container's
        # `xev -root` sink.
        screen.root.change_attributes(event_mask=X.KeyPressMask | X.ButtonPressMask)
        self.gc = self.window.create_gc()
        self.window.map()
        self.paint()

    def paint(self) -> None:
        width, height = self.screen_image.size
        data = _to_zpixmap(self.screen_image)
        stride = width * 4
        for top in range(0, height, BAND_ROWS):
            rows = min(BAND_ROWS, height - top)
            self.window.put_image(
                self.gc, 0, top, width, rows, X.ZPixmap, self.display.screen().root_depth, 0,
                data[top * stride:(top + rows) * stride],
            )
        self.display.flush()

    def handle_key(self, keycode: int) -> None:
        keysym = self.display.keycode_to_keysym(keycode, 0)
        self.show(self.keysym_to_key(keysym))

    def handle_button(self, x: int, y: int) -> None:
        self.show(click_targets.scene_at(x, y) or "")

    def show(self, key: str) -> None:
        path = self.scene_dir / f"{key}.png"
        if not key or not path.exists():
            return
        self.screen_image = Image.open(path)
        self.paint()

    def run(self) -> None:
        while True:
            event = self.display.next_event()
            if event.type == X.Expose:
                self.paint()
            elif event.type == X.KeyPress:
                self.handle_key(event.detail)
            elif event.type == X.ButtonPress:
                self.handle_button(event.event_x, event.event_y)

    @staticmethod
    def keysym_to_key(keysym: int) -> str:
        """XK.keysym_to_string() returns None for plain letters and digits, whose
        keysym value is already their ASCII code.

        Folded to lower case: a server that translates a keysym to its
        shifted twin still selects the scene it asked for, rather than none
        at all.
        """
        return chr(keysym).lower() if 0x20 <= keysym < 0x7F else ""


def _scene_dir() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(os.environ.get("SCENE_DIR", str(DEFAULT_SCENE_DIR)))


if __name__ == "__main__":
    ScenePlayer(_scene_dir()).run()
