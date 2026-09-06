from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from vncdotool import imagematch, pixelformat


def solid(colour: tuple[int, int, int], size: tuple[int, int] = (32, 24)) -> Image.Image:
    return Image.new("RGB", size, colour)


def patched(base: Image.Image, colour: tuple[int, int, int], size: int = 2) -> Image.Image:
    image = base.copy()
    ImageDraw.Draw(image).rectangle([8, 8, 8 + size - 1, 8 + size - 1], fill=colour)
    return image


def quantized(image: Image.Image, tolerance: tuple[int, int, int]) -> Image.Image:
    """`image` with each channel rounded down onto the grid a format with this
    tolerance can express."""
    bands = [band.point(lambda value, step=step: value & ~step) for band, step in zip(image.split(), tolerance)]
    return Image.merge("RGB", bands)


class TestWorstDelta(unittest.TestCase):
    def test_identical_screens_are_zero_apart(self) -> None:
        screen = solid((123, 45, 67))
        self.assertEqual(imagematch.worst_delta(screen, screen.copy()), 0)

    def test_black_against_white_is_most_of_the_scale(self) -> None:
        self.assertGreater(imagematch.worst_delta(solid((0, 0, 0)), solid((255, 255, 255))), 240)

    def test_a_luma_change_scores_above_a_chroma_change_of_the_same_size(self) -> None:
        grey = solid((100, 100, 100))
        luma = imagematch.worst_delta(grey, solid((108, 108, 108)))
        chroma = imagematch.worst_delta(grey, solid((100, 100, 108)))
        self.assertGreater(luma, chroma)

    def test_it_reports_the_worst_pixel_not_the_average(self) -> None:
        base = solid((30, 30, 30))
        self.assertEqual(
            imagematch.worst_delta(base, patched(base, (255, 0, 0))),
            imagematch.worst_delta(base, solid((255, 0, 0))),
        )

    def test_a_blur_pulls_a_small_change_down(self) -> None:
        base = solid((30, 30, 30))
        changed = patched(base, (255, 0, 0))
        self.assertLess(
            imagematch.worst_delta(base, changed, blur=2),
            imagematch.worst_delta(base, changed),
        )

    def test_a_blurred_small_change_still_outscores_a_blurred_identical_screen(self) -> None:
        base = solid((30, 30, 30))
        self.assertGreater(imagematch.worst_delta(base, patched(base, (255, 0, 0)), blur=2), 0)


class TestMatches(unittest.TestCase):
    def test_identical_screens_match_with_no_fuzz(self) -> None:
        screen = solid((123, 45, 67))
        self.assertTrue(imagematch.matches(screen, screen.copy(), 0))

    def test_a_screen_off_by_one_does_not_match_with_no_fuzz(self) -> None:
        self.assertFalse(imagematch.matches(solid((123, 45, 67)), solid((123, 45, 68)), 0))

    def test_a_screen_off_by_one_matches_within_fuzz(self) -> None:
        self.assertTrue(imagematch.matches(solid((123, 45, 67)), solid((123, 45, 68)), 4))

    def test_screens_of_different_sizes_never_match(self) -> None:
        self.assertFalse(
            imagematch.matches(solid((0, 0, 0), (32, 24)), solid((0, 0, 0), (16, 12)), 255)
        )

    def test_the_fast_path_agrees_with_the_score(self) -> None:
        """`matches` may answer from an RGB bound without scoring; where it
        does, it has to give the same answer scoring would."""
        base = solid((30, 30, 30))
        for other in (base.copy(), solid((31, 30, 30)), solid((30, 30, 45)), patched(base, (255, 0, 0))):
            for fuzz in (0, 1, 4, 16, 64, 255):
                with self.subTest(fuzz=fuzz, colour=other.getpixel((0, 0))):
                    self.assertEqual(
                        imagematch.matches(base, other, fuzz),
                        imagematch.worst_delta(base, other) <= fuzz,
                    )

    def test_a_blur_lets_a_small_change_pass_a_fuzz_it_would_otherwise_fail(self) -> None:
        base = solid((30, 30, 30))
        changed = patched(base, (255, 0, 0))
        fuzz = imagematch.worst_delta(base, changed, blur=2)
        self.assertTrue(imagematch.matches(base, changed, fuzz, blur=2))
        self.assertFalse(imagematch.matches(base, changed, fuzz))


class TestBoundForChannels(unittest.TestCase):
    def test_no_error_bounds_to_no_fuzz(self) -> None:
        self.assertEqual(imagematch.bound_for_channels((0, 0, 0)), 0)

    def test_it_bounds_whichever_way_the_channels_round(self) -> None:
        bound = imagematch.bound_for_channels((7, 3, 7))
        for red in (-7, 7):
            for green in (-3, 3):
                for blue in (-7, 7):
                    base = solid((128, 128, 128))
                    other = solid((128 + red, 128 + green, 128 + blue))
                    with self.subTest(offset=(red, green, blue)):
                        self.assertLessEqual(imagematch.worst_delta(base, other), bound)


class FormatFuzz:
    """One case per pixel format. Not a TestCase itself, so the loader
    collects it only through the subclasses load_tests builds.
    """

    name: str

    @property
    def pixel_format(self) -> pixelformat.PixelFormat:
        return pixelformat.PIXEL_FORMATS[self.name]

    def test_a_screen_the_format_quantized_matches_within_its_fuzz(self) -> None:
        tolerance = pixelformat.channel_tolerance(self.pixel_format)
        target = Image.new("RGB", (32, 24))
        target.putdata([(x * 8 % 256, y * 10 % 256, (x + y) * 6 % 256) for y in range(24) for x in range(32)])
        fuzz = imagematch.fuzz_for_format(self.pixel_format)
        self.assertTrue(  # type: ignore[attr-defined]
            imagematch.matches(quantized(target, tolerance), target, fuzz),
            f"{self.name} cannot express its own screen within {fuzz}",
        )

    def test_a_swapped_channel_does_not_match_within_its_fuzz(self) -> None:
        target = solid((200, 100, 50))
        swapped = solid((50, 100, 200))
        fuzz = imagematch.fuzz_for_format(self.pixel_format)
        self.assertFalse(  # type: ignore[attr-defined]
            imagematch.matches(swapped, target, fuzz),
            f"{self.name} accepted a swapped channel within {fuzz}",
        )


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """One case per pixel format, named after it, so a failure's test id says
    which format failed.
    """
    suite = unittest.TestSuite()
    for case in (TestWorstDelta, TestMatches, TestBoundForChannels):
        suite.addTests(loader.loadTestsFromTestCase(case))
    for name in sorted(pixelformat.PIXEL_FORMATS):
        built = type(f"TestFuzzFor_{name}", (FormatFuzz, unittest.TestCase), {"name": name})
        suite.addTest(built("test_a_screen_the_format_quantized_matches_within_its_fuzz"))
        suite.addTest(built("test_a_swapped_channel_does_not_match_within_its_fuzz"))
    return suite


if __name__ == "__main__":
    unittest.main()
