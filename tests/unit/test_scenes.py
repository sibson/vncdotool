from __future__ import annotations

import io
import unittest

from PIL import Image

from tests.goldens import scenes
from vncdotool import pixelformat


def quantize(image: Image.Image, pixel_format: pixelformat.PixelFormat) -> Image.Image:
    """The screen a client rebuilds after a server packed it into this format.

    The server keeps a channel's top bits and Pillow's unpacker replicates
    them back up to eight, so a value's low bits come from its own high ones.
    """
    def channel(value: int, maximum: int) -> int:
        bits = maximum.bit_length()
        kept = value >> (8 - bits)
        return (kept << (8 - bits)) | (kept >> (2 * bits - 8)) if bits < 8 else value

    maxima = (pixel_format.redmax, pixel_format.greenmax, pixel_format.bluemax)
    return image.convert("RGB").point(
        [channel(value, maximum) for maximum in maxima for value in range(256)]
    )


class TestScenes(unittest.TestCase):
    def test_base_has_more_than_one_colour(self) -> None:
        # A single-colour capture is what the fleet's readiness probe reads
        # as "this server has not drawn anything yet".
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

    def test_read_patch_rejects_an_unstamped_screen(self) -> None:
        self.assertIsNone(scenes.read_patch(scenes.base()))

    def test_read_patch_rejects_a_screen_too_small_to_hold_one(self) -> None:
        self.assertIsNone(scenes.read_patch(Image.new("RGB", (8, 8), (255, 255, 255))))

    def test_stamping_a_screen_too_small_to_hold_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            scenes.stamp_patch(Image.new("RGB", (8, 8)), "s")

    def test_every_glyph_is_distinct(self) -> None:
        self.assertEqual(len(set(scenes.GLYPHS.values())), len(scenes.SCENES))

    def test_every_scene_has_a_glyph(self) -> None:
        self.assertEqual(sorted(scenes.GLYPHS), sorted(scenes.SCENES))

    def test_every_glyph_is_the_declared_shape(self) -> None:
        columns, rows = scenes.GLYPH_SIZE
        for key, glyph in scenes.GLYPHS.items():
            with self.subTest(key=key):
                self.assertEqual(len(glyph), rows)
                self.assertEqual({len(line) for line in glyph}, {columns})
                self.assertEqual(set("".join(glyph)) - {"#", " "}, set())

    def test_reset_returns_the_base_screen(self) -> None:
        stamped = scenes.apply("0", scenes.apply("d", scenes.base()))
        expected = scenes.base()
        scenes.stamp_patch(expected, "0")
        self.assertEqual(stamped.tobytes(), expected.tobytes())


class JpegRoundTrip:
    """The glyph read back off a scene a lossy encoder has been through.

    Tight offers JPEG once a quality level is advertised, so a captured frame
    need not be the frame the scene player drew. Ink and paper differ only in
    luma, which JPEG keeps far better than chroma, and a cell is sampled at
    its centre rather than at the edges the ringing gathers on.
    """

    key: str
    quality: int

    def test_the_patch_names_its_own_scene(self) -> None:
        buffer = io.BytesIO()
        scenes.apply(self.key, scenes.base()).save(buffer, "JPEG", quality=self.quality, subsampling=2)
        buffer.seek(0)
        self.assertEqual(scenes.read_patch(Image.open(buffer)), self.key)


class PatchRoundTrip:
    """One scene's glyph, read back off the screen a given format rebuilds."""

    key: str
    pixel_format_name: str

    def test_the_patch_names_its_own_scene(self) -> None:
        screen = scenes.apply(self.key, scenes.base())
        rebuilt = quantize(screen, pixelformat.PIXEL_FORMATS[self.pixel_format_name])
        self.assertEqual(scenes.read_patch(rebuilt), self.key)


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """unittest's own hook for building a suite: one case per scene and format
    pair, so a failure's test id says which pair collapsed.
    """
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestScenes))
    for name in pixelformat.PIXEL_FORMATS:
        for key in scenes.SCENES:
            case = type(
                f"TestPatch_{name}_{key}",
                (PatchRoundTrip, unittest.TestCase),
                {"key": key, "pixel_format_name": name},
            )
            suite.addTest(case("test_the_patch_names_its_own_scene"))
    for quality in (95, 25):
        for key in scenes.SCENES:
            case = type(
                f"TestPatch_jpeg{quality}_{key}",
                (JpegRoundTrip, unittest.TestCase),
                {"key": key, "quality": quality},
            )
            suite.addTest(case("test_the_patch_names_its_own_scene"))
    return suite


if __name__ == "__main__":
    unittest.main()
