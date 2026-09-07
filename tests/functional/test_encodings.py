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
from typing import Dict, Set
from unittest import TestCase

from PIL import Image

from vncdotool import decoders

from .utils import SCENE_SERVERS, VNCServer, awaiting, run_vncdo, server_is_up

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"
SCENES = ("0", "s")

RECTANGLE_ENCODING = re.compile(r"Received <Encoding\.([A-Z_]+):")

# Measured against the fleet by offering one encoding at a time and reading
# back the encoding of the rectangles that arrived. Every server here
# answers with Raw for anything it does not implement, so an encoding is
# listed only where the server really sends it:
#
# TigerVNC 1.12.0 answers a CoRRE request with Raw, matching upstream's
# EncodeManager::supported(), which accepts only Raw, RRE, Hextile, ZRLE and
# Tight.
EMITTED: Dict[str, Set[str]] = {
    "tigervnc": {"raw", "rre", "hextile", "zrle", "tight"},
    "x11vnc": {"raw", "rre", "corre", "hextile", "zrle", "tight"},
    "wayvnc": {"raw", "zrle", "tight"},
}


def capture(test: TestCase, server: VNCServer, encodings: str, key: str) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            server, "--encodings", encodings,
            "key", key, *awaiting(key), "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(
                f"{server.name}: vncdo --encodings {encodings} failed "
                f"({result.returncode}): {result.stderr}"
            )
        return Image.open(path).convert("RGB").copy()


class FleetTestCase(TestCase):
    server: VNCServer

    def setUp(self) -> None:
        if not server_is_up(self.server):
            self.fail(
                f"{self.server.name} is not listening on {self.server.port}; "
                f"{self.server.how_to_start}"
            )


class RendersTheScene:
    """One encoding against one image the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    encoding: str
    scene: str

    def test_renders_the_scene(self) -> None:
        screen = capture(self, self.server, self.encoding, self.scene)
        oracle = Image.open(SCENES_DIR / f"{self.scene}.png").convert("RGB")
        self.assertEqual(screen.size, oracle.size)
        self.assertEqual(
            screen.tobytes(), oracle.tobytes(),
            f"{self.server.name}: {self.encoding} does not render scene "
            f"{self.scene} as the server was shown it",
        )


class EmitsTheEncoding:
    """Without this, the test above passes on a server that answered every request with Raw.

    x11vnc encodes a rectangle as Raw whenever RRE or CoRRE would need more
    subrectangles than its limit allows, so what it emits is a property of
    what is on screen: the flat scenes come back RRE, the dense and
    scattered ones Raw.
    """

    encoding: str
    scene = "0"

    def test_the_server_really_emits_the_encoding_we_asked_for(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_vncdo(
                self.server, "-v", "-v", "--encodings", self.encoding,
                "key", self.scene, *awaiting(self.scene),
                "capture", str(Path(tmp) / "screen.png"),
            )
        if result.returncode != 0:
            self.fail(
                f"{self.server.name}: vncdo --encodings {self.encoding} failed "
                f"({result.returncode}): {result.stderr}"
            )
        wanted = decoders.ENCODING_NAMES[self.encoding]
        arrived = set(RECTANGLE_ENCODING.findall(result.stderr))
        self.assertIn(
            wanted.name, arrived,
            f"no {wanted!r} rectangle arrived; {self.server.name} answered "
            f"with {sorted(arrived)}",
        )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for server in SCENE_SERVERS:
        label = server.name.replace("-", "_")
        for encoding in sorted(EMITTED[server.name]):
            name = f"TestEmits_{label}_{encoding}"
            case = type(
                name, (EmitsTheEncoding, FleetTestCase),
                {"server": server, "encoding": encoding},
            )
            suite.addTest(case("test_the_server_really_emits_the_encoding_we_asked_for"))
        for encoding in sorted(decoders.ENCODING_NAMES):
            for scene in SCENES:
                name = f"TestRenders_{label}_{encoding}_scene_{scene}"
                case = type(
                    name, (RendersTheScene, FleetTestCase),
                    {"server": server, "encoding": encoding, "scene": scene},
                )
                suite.addTest(case("test_renders_the_scene"))
    return suite
