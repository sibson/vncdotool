"""`stable` and `rstable` against a real server.

The window and the timeout are what is actually asserted here. The repaint
race that motivates the command -- test_scene_player.py captures behind a
`pause 0.3` because the player repaints asynchronously to the key event
reaching the X server -- does not reproduce against this fleet: a capture
taken with no wait at all reads the right scene every time, because
`capture` already blocks for a whole-screen update. So the two scene tests
below are smoke over a live server, not proof that `stable` closes a race.
Demonstrating that needs a fixture that animates and then stops, which the
scene player is not.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest import TestCase

from PIL import Image

from tests.goldens import scenes

from .utils import HOST, TIGERVNC, port_open, run_vncdo


class TestStable(TestCase):
    server = TIGERVNC

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.fail(
                f"{self.server.name} is not listening on {self.server.port}; "
                f"{self.server.how_to_start}"
            )

    def run_ok(self, *args: str, timeout: float | None = None):
        result = run_vncdo(self.server, *args, timeout=timeout)
        self.assertEqual(
            result.returncode,
            0,
            f"`vncdo {' '.join(args)}` exited {result.returncode}, "
            f"stderr:\n{result.stderr}",
        )
        return result

    def capture(self, *args: str) -> Image.Image:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            self.run_ok(*args, "capture", str(path))
            return Image.open(path).copy()

    def test_waits_out_the_window_it_was_given(self) -> None:
        started = time.monotonic()
        self.run_ok("stable", "1.5", "0")
        elapsed = time.monotonic() - started

        # The window cannot be observed to have passed before it has.
        self.assertGreaterEqual(elapsed, 1.5)

    def test_a_capture_behind_stable_still_shows_the_scene(self) -> None:
        self.run_ok("key", "0", "stable", "0.5", "0")

        screen = self.capture("key", "s", "stable", "0.5", "0")

        self.assertEqual(scenes.read_patch(screen), "s")

    def test_a_capture_behind_rstable_still_shows_the_scene(self) -> None:
        width, height = scenes.SIZE

        screen = self.capture(
            "key", "d", "rstable", "0.5", "0", "0", "0", str(width), str(height)
        )

        self.assertEqual(scenes.read_patch(screen), "d")

    def test_a_window_the_timeout_cannot_cover_exits_40(self) -> None:
        """A screen that never settles inside --timeout ends the run, not the wait."""
        result = run_vncdo(self.server, "--timeout", "2", "stable", "60", "0")

        self.assertEqual(
            result.returncode, 40, f"stderr:\n{result.stderr}"
        )
