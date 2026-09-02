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

from .utils import HOST, TIGERVNC, capture_through_vnclog, port_open, run_vncdo

SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"
SCENES = ("0", "s")
# vnclog listens here while it records what the server answered with.
PROXY_PORT = 5997

# tigervnc answers a CoRRE request with Raw: measured against the fleet's
# 1.12.0 in #417, and upstream's EncodeManager::supported() accepts Raw, RRE,
# Hextile, ZRLE and Tight only. Offering CoRRE here would prove the fallback
# renders, not that CoRRE does.
EMITTED_BY_TIGERVNC = {"raw", "rre", "hextile", "zrle"}


def capture(test: TestCase, encodings: str, key: str) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            TIGERVNC, "--encodings", encodings,
            "key", key, "pause", "0.3", "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(f"vncdo --encodings {encodings} failed ({result.returncode}): {result.stderr}")
        return Image.open(path).convert("RGB").copy()


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
        screen = capture(self, self.encoding, self.scene)
        oracle = Image.open(SCENES_DIR / f"{self.scene}.png").convert("RGB")
        self.assertEqual(screen.size, oracle.size)
        self.assertEqual(
            screen.tobytes(), oracle.tobytes(),
            f"{self.encoding} does not render scene {self.scene} as the server was shown it",
        )


class EmitsTheEncoding:
    """One encoding the server is asked for, and what it answered with.

    Without this the test above passes on a server that answered every
    request with Raw, which proves only that Raw still works. The witness is
    the capture archive's `encodings_seen`, tallied off the decoded server
    stream: a client log says no more than which encodings were offered.
    """

    encoding: str

    def test_the_server_really_emits_the_encoding_we_asked_for(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorded = capture_through_vnclog(
                self, TIGERVNC, PROXY_PORT,
                "--encodings", self.encoding, "capture", str(Path(tmp) / "screen.png"),
            )
        wanted = decoders.ENCODING_NAMES[self.encoding]
        answered = {seen["encoding"]: seen["rectangles"] for seen in recorded.meta["encodings_seen"]}
        self.assertIn(
            wanted.value, answered,
            f"no {wanted!r} rectangle arrived; tigervnc answered with {sorted(answered)}",
        )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """One case per encoding and scene, so a failure's test id names both."""
    suite = unittest.TestSuite()
    for encoding in sorted(EMITTED_BY_TIGERVNC):
        name = f"TestEmits_{encoding}"
        case = type(name, (EmitsTheEncoding, FleetTestCase), {"encoding": encoding})
        suite.addTest(case("test_the_server_really_emits_the_encoding_we_asked_for"))
    for encoding in sorted(decoders.ENCODING_NAMES):
        for scene in SCENES:
            name = f"TestRenders_{encoding}_scene_{scene}"
            case = type(
                name, (RendersTheScene, FleetTestCase),
                {"encoding": encoding, "scene": scene},
            )
            suite.addTest(case("test_renders_the_scene"))
    return suite
