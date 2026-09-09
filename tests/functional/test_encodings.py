"""Each selectable encoding, live against the fleet, on the oracle images.

The offline half is tests/unit/test_decoders.py, whose bytes come from the
specification. This half catches what a hand-built fixture cannot:
negotiation, rectangle ordering, and whether a real server's idea of the
encoding matches ours. See specs/decoder-goldens.md.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Set, Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import decoders

from .utils import (
    SCENE_SERVERS,
    SCENES_DIR,
    FleetTestCase,
    VNCServer,
    awaiting,
    run_vncdo,
)

SCENES = ("0", "s")
# Flat enough that every server encodes it the way it was asked to.
HONOURED_SCENE = "0"

RECTANGLE_ENCODING = re.compile(r"Received <Encoding\.([A-Z_]+):")

# Measured against the fleet by offering one encoding at a time and reading
# back the encoding of the rectangles that arrived. Every server here
# answers with Raw for anything it does not implement, so an encoding is
# listed only where the server really sends it.
EMITTED: Dict[str, Set[str]] = {
    "tigervnc": {"raw", "rre", "hextile", "zrle", "tight"},
    "x11vnc": {"raw", "rre", "corre", "hextile", "zrle", "tight"},
    "wayvnc": {"raw", "zrle", "tight"},
    "selenoid": {"raw", "rre", "hextile", "zrle", "tight"},
    "kasmvnc": {"raw", "rre", "hextile", "zrle", "tight"},
}


def capture(
    test: TestCase, server: VNCServer, encodings: str, key: str
) -> Tuple[Image.Image, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            server, "-v", "-v", "--encodings", encodings,
            "key", key, *awaiting(key), "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(
                f"{server.name}: vncdo --encodings {encodings} failed "
                f"({result.returncode}): {result.stderr}"
            )
        return Image.open(path).convert("RGB").copy(), result.stderr


class RendersTheScene:
    """One encoding against one image the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    encoding: str
    scene: str

    def test_renders_the_scene_through_the_encoding_it_asked_for(self) -> None:
        screen, log = capture(self, self.server, self.encoding, self.scene)
        oracle = Image.open(SCENES_DIR / f"{self.scene}.png").convert("RGB")
        self.assertEqual(screen.size, oracle.size)
        self.assertEqual(
            screen.tobytes(), oracle.tobytes(),
            f"{self.server.name}: {self.encoding} does not render scene "
            f"{self.scene} as the server was shown it",
        )

        # A server answers with Raw for an encoding it does not implement,
        # and Raw renders the scene correctly, so the comparison above passes
        # either way. Only on HONOURED_SCENE: x11vnc falls back to Raw once
        # RRE or CoRRE would need more subrectangles than its limit allows.
        if self.scene != HONOURED_SCENE or self.encoding not in EMITTED[self.server.name]:
            return
        wanted = decoders.ENCODING_NAMES[self.encoding]
        arrived = set(RECTANGLE_ENCODING.findall(log))
        self.assertIn(
            wanted.name, arrived,
            f"no {wanted!r} rectangle arrived; {self.server.name} answered "
            f"with {sorted(arrived)}",
        )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for server in SCENE_SERVERS:
        label = server.name.replace("-", "_")
        for encoding in sorted(decoders.ENCODING_NAMES):
            for scene in SCENES:
                name = f"TestRenders_{label}_{encoding}_scene_{scene}"
                case = type(
                    name, (RendersTheScene, FleetTestCase),
                    {"server": server, "encoding": encoding, "scene": scene},
                )
                suite.addTest(case("test_renders_the_scene_through_the_encoding_it_asked_for"))
    return suite
