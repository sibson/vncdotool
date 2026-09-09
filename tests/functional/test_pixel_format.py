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
from typing import Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import pixelformat

from .imagediff import assert_images_match
from .utils import (
    SCENE_SERVERS,
    SCENES_DIR,
    FleetTestCase,
    VNCServer,
    awaiting,
    run_vncdo,
)

# 32bpp throughout, so the only difference is the order of the channels and
# a mismatched raw mode shows up as swapped colour rather than as noise a
# tolerance could hide. A reduced format cannot be compared this way: the
# scene player's key patch does not survive quantization, so the driver
# cannot tell which scene it is looking at.
FORMATS = ("bgrx8888", "rgbx8888")
SCENES = ("0", "s", "d")


def capture(
    test: TestCase, server: VNCServer, pixel_format: str, key: str
) -> Tuple[Image.Image, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            server, "-v", "--pixel-format", pixel_format,
            "key", key, *awaiting(key), "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(
                f"{server.name}: vncdo --pixel-format {pixel_format} failed "
                f"({result.returncode}): {result.stderr}"
            )
        return Image.open(path).convert("RGB").copy(), result.stderr


class RendersTheScene:
    """One format against one image the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    pixel_format: str
    scene: str

    def test_renders_the_scene(self) -> None:
        screen, _ = capture(self, self.server, self.pixel_format, self.scene)
        oracle = Image.open(SCENES_DIR / f"{self.scene}.png").convert("RGB")
        assert_images_match(
            self, screen, oracle,
            f"{self.server.name}-{self.pixel_format}-scene-{self.scene}",
            message=f"{self.server.name}: {self.pixel_format} does not "
                    "render the image the server was shown",
        )


class Negotiation:
    pixel_format: str

    def test_the_server_sends_the_format_it_is_asked_for(self) -> None:
        """Nothing on the wire acknowledges SetPixelFormat: a server that
        ignored it would keep sending its own, and the client -- reading at
        the width it asked for -- would desync rather than paint the scene.
        So rendering the scene is what proves the request was honoured, and
        it is the only thing that can.
        """
        fmt = pixelformat.PIXEL_FORMATS[self.pixel_format]
        tolerance = max(255 // maximum for maximum in (fmt.redmax, fmt.greenmax, fmt.bluemax))
        screen, log = capture(self, self.server, self.pixel_format, "s")
        self.assertIn(f"Requesting {fmt}", log)
        oracle = Image.open(SCENES_DIR / "s.png").convert("RGB")
        assert_images_match(
            self, screen, oracle,
            f"{self.server.name}-{self.pixel_format}-scene-s",
            tolerance=tolerance,
            message=f"{self.server.name}: {self.pixel_format} differs by more "
                    "than its own quantization allows",
        )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for server in SCENE_SERVERS:
        label = server.name.replace("-", "_")
        for pixel_format in sorted(pixelformat.PIXEL_FORMATS):
            name = f"TestNegotiation_{label}_{pixel_format}"
            case = type(
                name, (Negotiation, FleetTestCase),
                {"server": server, "pixel_format": pixel_format},
            )
            suite.addTest(case("test_the_server_sends_the_format_it_is_asked_for"))
        for pixel_format in FORMATS:
            for scene in SCENES:
                name = f"TestRenders_{label}_{pixel_format}_scene_{scene}"
                case = type(
                    name, (RendersTheScene, FleetTestCase),
                    {"server": server, "pixel_format": pixel_format, "scene": scene},
                )
                suite.addTest(case("test_renders_the_scene"))
    return suite
