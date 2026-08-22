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

from .vncservers import HOST, TIGERVNC, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"
SCENES = ("0", "s")

# tigervnc answers a request for CoRRE with Raw (see the fleet encoding
# support table in specs/decoder-architecture.md), so offering it proves the
# fallback renders, not that CoRRE does.
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
    """One encoding against the images the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    encoding: str

    def test_renders_every_scene(self) -> None:
        for key in SCENES:
            with self.subTest(scene=key):
                screen, _ = capture(self, self.encoding, key)
                oracle = Image.open(SCENES_DIR / f"{key}.png").convert("RGB")
                self.assertEqual(screen.size, oracle.size)
                self.assertEqual(
                    screen.tobytes(), oracle.tobytes(),
                    f"{self.encoding} does not render the image the server was shown",
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
    """One case per encoding, so a failure's test id says which one failed."""
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestNegotiation))
    for encoding in sorted(decoders.ENCODING_NAMES):
        name = f"TestRenders_{encoding}"
        case = type(name, (RendersTheScene, FleetTestCase), {"encoding": encoding})
        suite.addTest(case("test_renders_every_scene"))
    return suite
