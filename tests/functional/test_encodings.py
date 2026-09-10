"""Each selectable encoding, live against the fleet, on the oracle images.

The offline half is tests/unit/test_decoders.py, whose bytes come from the
specification. This half catches what a hand-built fixture cannot:
negotiation, rectangle ordering, and whether a real server's idea of the
encoding matches ours. See specs/decoder-goldens.md.
"""
from __future__ import annotations

import re
import time
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple
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


# `cls N` repaints OVMF's whole shell framebuffer in colour N.
QEMU_SCREENS = {
    "flat": ("cls 4",),
    "text": ("cls 1", "echo vncdotool encoding probe"),
}

# Measured against QEMU's firmware screens the way EMITTED was.
QEMU_EMITTED = {"raw", "hextile", "zrle", "tight"}

SETTLE_DELAY = 0.5
SETTLE_ATTEMPTS = 12


def capture_current(test: TestCase, encoding: str) -> Tuple[Image.Image, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        result = run_vncdo(QEMU, "-v", "-v", "--encodings", encoding, "capture", str(path))
        if result.returncode != 0:
            test.fail(
                f"qemu: vncdo --encodings {encoding} failed "
                f"({result.returncode}): {result.stderr}"
            )
        return Image.open(path).convert("RGB").copy(), result.stderr


def type_commands(test: TestCase, commands: Tuple[str, ...]) -> None:
    argv: List[str] = []
    for command in commands:
        argv += ["type", command, "key", "enter"]
    result = run_vncdo(QEMU, *argv)
    if result.returncode != 0:
        test.fail(f"qemu: vncdo {' '.join(argv)} failed ({result.returncode}): {result.stderr}")


def settled(test: TestCase) -> Image.Image:
    """A Raw capture, once two in a row agree.

    The shell redraws over several updates, and the firmware is still
    booting when the fleet first comes up, so a single capture can catch a
    half-drawn screen that the next encoding would never reproduce.
    """
    previous = None
    for _ in range(SETTLE_ATTEMPTS):
        current, _ = capture_current(test, "raw")
        if previous is not None and current.tobytes() == previous.tobytes():
            return current
        previous = current
        time.sleep(SETTLE_DELAY)
    test.fail(f"qemu: screen never settled over {SETTLE_ATTEMPTS} captures")


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


class RendersTheSameScreenAsRaw:
    """One encoding against QEMU's own Raw, on a screen the shell was told to draw."""

    server = QEMU
    encoding: str
    screen: str

    def test_renders_the_screen_as_raw_renders_it(self) -> None:
        type_commands(self, QEMU_SCREENS[self.screen])
        oracle = settled(self)
        screen, log = capture_current(self, self.encoding)
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


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for encoding in sorted(decoders.ENCODING_NAMES):
        for screen in sorted(QEMU_SCREENS):
            name = f"TestRendersAsRaw_qemu_{encoding}_screen_{screen}"
            case = type(
                name, (RendersTheSameScreenAsRaw, FleetTestCase),
                {"encoding": encoding, "screen": screen},
            )
            suite.addTest(case("test_renders_the_screen_as_raw_renders_it"))
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
