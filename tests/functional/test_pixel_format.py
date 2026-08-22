"""The framebuffer a client sees does not depend on the pixel format it
negotiated, checked against a live server.

The offline half is in tests/unit/test_goldens.py and compares committed
captures. This half needs no fixture: it drives one server at each format
in turn and compares what comes back.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from PIL import Image

from vncdotool import pixelformat

from .imagediff import assert_images_match
from .utils import HOST, TIGERVNC, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"

# 32bpp throughout, so the only difference is the order of the channels and
# a mismatched raw mode shows up as swapped colour rather than as noise a
# tolerance could hide. A reduced format cannot be compared this way: the
# scene player's key patch does not survive quantization, so the driver
# cannot tell which scene it is looking at.
FORMATS = ("bgrx8888", "rgbx8888")
SCENES = ("0", "s", "d")


def capture(test: TestCase, pixel_format: str, key: str) -> tuple[Image.Image, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            TIGERVNC, "-v", "--pixel-format", pixel_format,
            "key", key, "pause", "0.3", "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(f"vncdo --pixel-format {pixel_format} failed ({result.returncode}): {result.stderr}")
        return Image.open(path).convert("RGB").copy(), result.stderr


class FleetTestCase(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")


class RendersTheScene:
    """One format against the images the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    pixel_format: str

    def test_renders_every_scene(self) -> None:
        for key in SCENES:
            with self.subTest(scene=key):
                screen, _ = capture(self, self.pixel_format, key)
                oracle = Image.open(SCENES_DIR / f"{key}.png").convert("RGB")
                assert_images_match(
                    self, screen, oracle, f"{self.pixel_format}-scene-{key}",
                    message=f"{self.pixel_format} does not render the image the server was shown",
                )


class TestNegotiation(FleetTestCase):
    def test_the_server_sends_every_format_it_is_asked_for(self) -> None:
        """Nothing on the wire acknowledges SetPixelFormat: a server that
        ignored it would keep sending its own, and the client -- reading at
        the width it asked for -- would desync rather than paint the scene.
        So rendering the scene is what proves the request was honoured, and
        it is the only thing that can.
        """
        oracle = Image.open(SCENES_DIR / "s.png").convert("RGB")
        for name in sorted(pixelformat.PIXEL_FORMATS):
            with self.subTest(pixel_format=name):
                fmt = pixelformat.PIXEL_FORMATS[name]
                tolerance = max(255 // maximum for maximum in (fmt.redmax, fmt.greenmax, fmt.bluemax))
                screen, log = capture(self, name, "s")
                self.assertIn(f"Requesting {fmt}", log)
                assert_images_match(
                    self, screen, oracle, f"{name}-scene-s", tolerance=tolerance,
                    message=f"{name} differs by more than its own quantization allows",
                )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """One case per format, so a failure's test id says which one failed."""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestNegotiation))
    for pixel_format in FORMATS:
        name = f"TestRenders_{pixel_format}"
        case = type(name, (RendersTheScene, FleetTestCase), {"pixel_format": pixel_format})
        suite.addTest(case("test_renders_every_scene"))
    return suite
