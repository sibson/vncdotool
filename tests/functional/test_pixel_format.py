"""R3, live: the framebuffer does not depend on the negotiated pixel format.

The offline half of this lives in tests/unit/test_goldens.py and compares
committed captures. This half needs no fixture: it drives one server at
each format in turn and compares what comes back.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from tests.goldens import scenes
from vncdotool import pixelformat

from .vncservers import HOST, TIGERVNC, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"

# 32bpp throughout, so the only difference is the order of the channels and
# a mismatched raw mode shows up as swapped colour rather than as noise a
# tolerance could hide. A reduced format cannot be compared this way: the
# scene player's key patch does not survive quantization, so the driver
# cannot tell which scene it is looking at.
FORMATS = ("bgrx8888", "rgbx8888")


class TestPixelFormatIndependence(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")

    def _capture(self, pixel_format: str, key: str) -> Image.Image:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            result = run_vncdo(
                TIGERVNC, "--pixel-format", pixel_format,
                "key", key, "pause", "0.3", "capture", str(path),
            )
            if result.returncode != 0:
                self.fail(f"vncdo --pixel-format {pixel_format} failed ({result.returncode}): {result.stderr}")
            return Image.open(path).convert("RGB").copy()

    def test_every_format_decodes_the_scene_the_same_way(self) -> None:
        for key in ("0", "s", "d"):
            oracle = Image.open(SCENES_DIR / f"{key}.png").convert("RGB")
            for pixel_format in FORMATS:
                with self.subTest(scene=key, pixel_format=pixel_format):
                    screen = self._capture(pixel_format, key)
                    self.assertEqual(screen.size, oracle.size)
                    self.assertEqual(
                        screen.tobytes(), oracle.tobytes(),
                        f"scene {key} at {pixel_format} does not match the image the server was shown",
                    )

    def test_the_server_is_asked_for_every_format_we_offer(self) -> None:
        """A format the server refuses would otherwise pass as a silent no-op,
        since it keeps sending its own and the client keeps decoding it.
        """
        for name in sorted(pixelformat.PIXEL_FORMATS):
            with self.subTest(pixel_format=name):
                result = run_vncdo(TIGERVNC, "-v", "--pixel-format", name, "pause", "0")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Requesting", result.stderr)

    def test_the_scene_key_patch_survives_a_reordered_format(self) -> None:
        self.assertEqual(scenes.read_patch(self._capture("rgbx8888", "g")), "g")
