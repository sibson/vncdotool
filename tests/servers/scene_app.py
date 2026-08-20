#!/usr/bin/env python3
"""Fullscreen X client that paints a scene per keypress, for golden capture.

Runs inside the fleet containers. Scenes are composed in memory and pushed
whole with PutImage, so what reaches the X framebuffer is a buffer this
process holds rather than the result of a rendering stack -- that buffer,
saved as a PNG, is the oracle a golden fixture is checked against.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image
from Xlib import X, display

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.servers import scenes  # noqa: E402

ORACLE_DIR = Path(os.environ.get("SCENE_ORACLE_DIR", "/oracles"))
# PutImage carries the whole request in one X message; splitting into bands
# keeps every request well inside the server's maximum request length.
BAND_ROWS = 32


def _to_zpixmap(image: Image.Image) -> bytes:
    """Depth-24 ZPixmap data: B, G, R, pad per pixel on an LSBFirst server."""
    return image.convert("RGB").tobytes("raw", "BGRX")


class SceneApp:
    def __init__(self) -> None:
        self.display = display.Display()
        if self.display.display.info.image_byte_order != 0:
            raise SystemExit("scene_app: X server is not LSBFirst; ZPixmap byte order would be wrong")
        screen = self.display.screen()
        width, height = scenes.SIZE
        self.window = screen.root.create_window(
            0, 0, width, height, 0, screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=screen.black_pixel,
            override_redirect=True,
            event_mask=X.ExposureMask,
        )
        # Keys are watched on the root rather than on this window, so they
        # keep propagating there for the container's `xev -root` sink. A
        # key mask is per-client, so both of us receive every press.
        screen.root.change_attributes(event_mask=X.KeyPressMask)
        self.gc = self.window.create_gc()
        self.window.map()
        self.screen_image = scenes.base()
        scenes.stamp_patch(self.screen_image, "0")
        self.applied = 0
        ORACLE_DIR.mkdir(parents=True, exist_ok=True)
        self.paint()
        self.write_oracle("0")

    def paint(self) -> None:
        width, height = scenes.SIZE
        data = _to_zpixmap(self.screen_image)
        stride = width * 4
        for top in range(0, height, BAND_ROWS):
            rows = min(BAND_ROWS, height - top)
            self.window.put_image(
                self.gc, 0, top, width, rows, X.ZPixmap, self.display.screen().root_depth, 0,
                data[top * stride:(top + rows) * stride],
            )
        self.display.flush()

    def write_oracle(self, key: str) -> None:
        self.applied += 1
        self.screen_image.save(ORACLE_DIR / f"oracle-{self.applied:02d}-{key}.png")

    def handle_key(self, keycode: int) -> None:
        keysym = self.display.keycode_to_keysym(keycode, 0)
        key = keysym_to_key(keysym)
        if key not in scenes.SCENES:
            return
        self.screen_image = scenes.apply(key, self.screen_image)
        self.paint()
        self.write_oracle(key)

    def run(self) -> None:
        while True:
            event = self.display.next_event()
            if event.type == X.Expose:
                self.paint()
            elif event.type == X.KeyPress:
                self.handle_key(event.detail)


def keysym_to_key(keysym: int) -> str:
    """XK.keysym_to_string() returns None for plain letters and digits, whose
    keysym value is already their ASCII code.
    """
    return chr(keysym) if 0x20 <= keysym < 0x7F else ""


if __name__ == "__main__":
    SceneApp().run()
