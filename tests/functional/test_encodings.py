"""Each selectable encoding, live against the fleet, on the oracle images.

The offline half is tests/unit/test_decoders.py, whose bytes come from the
specification. This half catches what a hand-built fixture cannot:
negotiation, rectangle ordering, and whether a real server's idea of the
encoding matches ours. See specs/decoder-goldens.md.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from PIL import Image

from vncdotool import decoders

from .utils import HOST, TIGERVNC, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"
SCENES = ("0", "s")

# tigervnc answers a CoRRE request with Raw: measured against the fleet's
# 1.12.0 in #417, and upstream's EncodeManager::supported() accepts Raw, RRE,
# Hextile, ZRLE and Tight only. Offering CoRRE here would prove the fallback
# renders, not that CoRRE does.
EMITTED_BY_TIGERVNC = {"raw", "rre"}


def capture(test: TestCase, encodings: str, key: str) -> tuple[Image.Image, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            TIGERVNC, "-v", "--encodings", encodings,
            "key", key, "pause", "0.3", "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(f"vncdo --encodings {encodings} failed ({result.returncode}): {result.stderr}")
        return Image.open(path).convert("RGB").copy(), result.stderr


class FleetTestCase(TestCase):
    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(f"{TIGERVNC.name} is not listening on {TIGERVNC.port}; {TIGERVNC.how_to_start}")


class RendersTheScene:
    """One encoding against one image the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    encoding: str
    scene: str

    def test_renders_the_scene(self) -> None:
        screen, _ = capture(self, self.encoding, self.scene)
        oracle = Image.open(SCENES_DIR / f"{self.scene}.png").convert("RGB")
        self.assertEqual(screen.size, oracle.size)
        self.assertEqual(
            screen.tobytes(), oracle.tobytes(),
            f"{self.encoding} does not render scene {self.scene} as the server was shown it",
        )


class TestNegotiation(FleetTestCase):
    def test_the_server_really_emits_the_encoding_we_asked_for(self) -> None:
        """Without this the test above passes on a server that answered every
        request with Raw, which proves only that Raw still works.
        """
        for name in sorted(EMITTED_BY_TIGERVNC):
            with self.subTest(encoding=name):
                _, log = capture(self, name, "s")
                wanted = decoders.ENCODING_NAMES[name]
                self.assertIn(
                    repr(wanted), log,
                    f"no {wanted!r} rectangle arrived; tigervnc answered with something else",
                )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """One case per encoding and scene, so a failure's test id names both."""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestNegotiation))
    for encoding in sorted(decoders.ENCODING_NAMES):
        for scene in SCENES:
            name = f"TestRenders_{encoding}_scene_{scene}"
            case = type(
                name, (RendersTheScene, FleetTestCase),
                {"encoding": encoding, "scene": scene},
            )
            suite.addTest(case("test_renders_the_scene"))
    return suite
