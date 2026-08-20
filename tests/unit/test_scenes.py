"""The scene generator behind the committed PNGs in tests/goldens/scenes/."""
from __future__ import annotations

import unittest

from tests.goldens import scenes


class TestScenes(unittest.TestCase):
    def test_base_is_not_flat(self) -> None:
        # A flat screen is indistinguishable from "no update arrived".
        self.assertGreater(len(scenes.base().getcolors(maxcolors=4096) or []), 1)

    def test_base_is_the_declared_size(self) -> None:
        self.assertEqual(scenes.base().size, scenes.SIZE)

    def test_every_key_is_deterministic(self) -> None:
        for key in scenes.SCENES:
            with self.subTest(key=key):
                first = scenes.apply(key, scenes.base())
                second = scenes.apply(key, scenes.base())
                self.assertEqual(first.tobytes(), second.tobytes())

    def test_scenes_depend_on_the_prior_screen(self) -> None:
        # An update is a delta, so "c" scrolling a solid screen and "c"
        # scrolling a dense one must not produce the same result.
        solid = scenes.apply("s", scenes.base())
        dense = scenes.apply("d", scenes.base())
        self.assertNotEqual(
            scenes.apply("c", solid).tobytes(),
            scenes.apply("c", dense).tobytes(),
        )

    def test_patch_round_trips_for_every_key(self) -> None:
        for key in scenes.SCENES:
            with self.subTest(key=key):
                self.assertEqual(scenes.read_patch(scenes.apply(key, scenes.base())), key)

    def test_read_patch_rejects_an_unstamped_screen(self) -> None:
        self.assertIsNone(scenes.read_patch(scenes.base()))

    def test_reset_returns_the_base_screen(self) -> None:
        stamped = scenes.apply("0", scenes.apply("d", scenes.base()))
        expected = scenes.base()
        scenes.stamp_patch(expected, "0")
        self.assertEqual(stamped.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
