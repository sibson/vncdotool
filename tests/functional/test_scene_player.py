"""The in-container scene player, exercised through a real server."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from tests.goldens import scenes

from .utils import TIGERVNC, port_open, HOST, run_vncdo


class TestScenePlayer(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")

    def _capture(self, *args: str) -> Image.Image:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            # The player repaints asynchronously to the key event reaching
            # the X server, so an immediate capture can still see the prior frame.
            result = run_vncdo(TIGERVNC, *args, "pause", "0.3", "capture", str(path))
            if result.returncode != 0:
                self.fail(f"vncdo failed ({result.returncode}): {result.stderr}")
            return Image.open(path).copy()

    def test_serves_the_golden_geometry(self) -> None:
        self.assertEqual(self._capture("key", "0").size, scenes.SIZE)

    def test_a_scene_key_changes_the_screen(self) -> None:
        reset = self._capture("key", "0")
        solid = self._capture("key", "s")
        self.assertNotEqual(reset.tobytes(), solid.tobytes())

    def test_the_patch_names_the_key_that_was_pressed(self) -> None:
        for key in ("0", "s", "d", "g"):
            with self.subTest(key=key):
                self.assertEqual(scenes.read_patch(self._capture("key", key)), key)
