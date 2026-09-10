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
from typing import Dict, Iterator, List, Set, Tuple
from unittest import TestCase

from PIL import Image

from vncdotool import decoders

from .utils import (
    QEMU,
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

RECTANGLE_ENCODING = re.compile(r"Received ([A-Z_]+) \(-?\d+\) rectangle")

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
    test: TestCase, server: VNCServer, encodings: str, *before: str
) -> Tuple[Image.Image, str]:
    """The screen `before` leaves behind, and the log naming its rectangles."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(
            server, "-v", "-v", "--encodings", encodings, *before, "capture", str(path),
        )
        if result.returncode != 0:
            test.fail(
                f"{server.name}: vncdo --encodings {encodings} failed "
                f"({result.returncode}): {result.stderr}"
            )
        return Image.open(path).convert("RGB").copy(), result.stderr


QEMU_SCREENS = {
    "flat": ("cls 4",),  # `cls N` repaints OVMF's whole shell framebuffer in colour N
    "text": ("cls 1", "echo vncdotool encoding probe"),
}

# Offered one at a time; QEMU sent these and answered with Raw for the rest.
QEMU_EMITTED = {"raw", "hextile", "zrle", "tight"}

# The shell answers a command over several framebuffer updates, so a capture
# taken as soon as the last key is sent can catch it half-drawn.
QEMU_SETTLE_SECONDS = "1"


def draw_on_qemu(test: TestCase, screen: str) -> Image.Image:
    """Put one of QEMU_SCREENS up, and return the Raw capture of it."""
    argv: List[str] = []
    for command in QEMU_SCREENS[screen]:
        argv += ["type", command, "key", "enter"]
    argv += ["stable", QEMU_SETTLE_SECONDS]
    oracle, _ = capture(test, QEMU, "raw", *argv)
    return oracle


class RendersTheScene:
    """One encoding against one image the server was shown.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    encoding: str
    scene: str

    def test_renders_the_scene_through_the_encoding_it_asked_for(self) -> None:
        screen, log = capture(
            self, self.server, self.encoding, "key", self.scene, *awaiting(self.scene)
        )
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


class RendersTheSameScreenAsRaw:
    """One encoding against QEMU's own Raw, on a screen the shell was told to draw."""

    server = QEMU
    encoding: str
    screen: str

    def test_renders_the_screen_as_raw_renders_it(self) -> None:
        oracle = draw_on_qemu(self, self.screen)
        screen, log = capture(self, QEMU, self.encoding)
        self.assertEqual(
            screen.tobytes(), oracle.tobytes(),
            f"qemu: {self.encoding} and raw disagree about the {self.screen} screen",
        )

        if self.encoding not in QEMU_EMITTED:
            return
        wanted = decoders.ENCODING_NAMES[self.encoding]
        arrived = set(RECTANGLE_ENCODING.findall(log))
        self.assertIn(
            wanted.name, arrived,
            f"no {wanted!r} rectangle arrived; qemu answered with {sorted(arrived)}",
        )


def qemu_cases() -> Iterator[TestCase]:
    """One case per encoding against each firmware screen."""
    for encoding in sorted(decoders.ENCODING_NAMES):
        for screen in sorted(QEMU_SCREENS):
            name = f"TestRendersAsRaw_qemu_{encoding}_screen_{screen}"
            case = type(
                name, (RendersTheSameScreenAsRaw, FleetTestCase),
                {"encoding": encoding, "screen": screen},
            )
            yield case("test_renders_the_screen_as_raw_renders_it")


def scene_cases() -> Iterator[TestCase]:
    """One case per encoding against each scene, on every server running the player."""
    for server in SCENE_SERVERS:
        label = server.name.replace("-", "_")
        for encoding in sorted(decoders.ENCODING_NAMES):
            for scene in SCENES:
                name = f"TestRenders_{label}_{encoding}_scene_{scene}"
                case = type(
                    name, (RendersTheScene, FleetTestCase),
                    {"server": server, "encoding": encoding, "scene": scene},
                )
                yield case("test_renders_the_scene_through_the_encoding_it_asked_for")


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(qemu_cases())
    suite.addTests(scene_cases())
    return suite
