"""Replay committed decoder goldens. No fleet, no network, no reactor.

Capture these with `make goldens`; see specs/decoder-goldens.md.
"""
from __future__ import annotations

import gzip
import json
import unittest
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

from PIL import Image

from vncdotool import client, imagematch, pixelformat

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "goldens"
SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"

TOLERANCE_KINDS = ("format-quantization", "jpeg-lossy")


class Fixture:
    """One committed capture: the bytes, what they were captured at, and a
    client that replays them the way they were recorded.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.conditions = json.loads((path / "conditions.json").read_text())

    @property
    def tolerance(self) -> Tuple[int, int, int]:
        red, green, blue = self.conditions["tolerance"]
        return red, green, blue

    @property
    def fuzz(self) -> float:
        return self.conditions["fuzz"]

    @property
    def blur(self) -> int:
        return self.conditions["blur"]

    @property
    def tolerance_kind(self) -> str:
        return self.conditions["tolerance_kind"]

    def mismatch(self, actual: Image.Image, expected: Image.Image) -> Optional[str]:
        """Why this frame is not its oracle, or None if it is.

        The two kinds are unrelated numbers: a format's quantization is a
        per-channel step it cannot land between, while a lossy encoder's error
        is a perceived distance that only a blur brings back under a bound.
        """
        if self.tolerance_kind == "jpeg-lossy":
            if imagematch.matches(actual, expected, self.fuzz, self.blur):
                return None
            worst = imagematch.worst_delta(actual, expected, self.blur)
            return f"{worst:.1f} from its oracle, further than {self.fuzz} at blur {self.blur}"
        difference = first_difference(actual, expected, self.tolerance)
        if difference is None:
            return None
        x, y, got, want = difference
        return f"pixel ({x},{y}) decoded {got}, expected {want}"

    def steps(self) -> List[Path]:
        return sorted(self.path.glob("step-*.bin.gz"))

    def client(self) -> client.VNCDoToolClient:
        cli = client.VNCDoToolClient()
        cli.transport = mock.Mock()
        cli.factory = mock.Mock()
        cli.factory.shared = 0
        cli.factory.password = None
        cli.factory.nocursor = False
        cli.factory.pseudocursor = False
        cli.factory.pseudodesktop = False
        cli.factory.last_rect = False
        cli.factory.qemu_extended_key = False
        cli.requested_pixel_format = pixelformat.PIXEL_FORMATS[self.conditions["pixel_format"]]
        cli.dataReceived(gzip.decompress((self.path / "init.bin.gz").read_bytes()))
        return cli


def fixtures() -> List[Fixture]:
    return [
        Fixture(path)
        for path in sorted(FIXTURE_ROOT.iterdir())
        if (path / "conditions.json").exists()
    ]


def first_difference(
    actual: Image.Image, expected: Image.Image, tolerance: Tuple[int, int, int]
) -> Optional[Tuple[int, int, tuple, tuple]]:
    """The first pixel further from its oracle than the format can account for.

    Per channel: rgb565's 6-bit green permits half the error its 5-bit red and
    blue do.
    """
    left, right = actual.convert("RGB").tobytes(), expected.convert("RGB").tobytes()
    if actual.size != expected.size:
        raise AssertionError(f"decoded {actual.size}, expected {expected.size}")
    width, _ = actual.size
    for offset in range(0, len(left), 3):
        got, want = left[offset:offset + 3], right[offset:offset + 3]
        if any(abs(a - b) > bound for a, b, bound in zip(got, want, tolerance)):
            pixel = offset // 3
            return pixel % width, pixel // width, tuple(got), tuple(want)
    return None


class TestGoldens(unittest.TestCase):
    def test_at_least_one_fixture_is_committed(self) -> None:
        self.assertTrue(fixtures(), f"no golden fixtures under {FIXTURE_ROOT}; capture one with `make goldens`")


class GoldenReplay:
    """The body of a per-fixture case. Not a TestCase itself, so the loader
    collects it only through the subclasses load_tests builds.
    """

    fixture: Fixture

    def test_says_which_kind_of_tolerance_it_carries(self) -> None:
        fixture = self.fixture
        self.assertIn(  # type: ignore[attr-defined]
            fixture.tolerance_kind, TOLERANCE_KINDS,
            "a fixture must say whether its tolerance bounds the format's "
            "quantization or a lossy encoding's error; the two are unrelated "
            "numbers and only one of them falls out of the pixel format",
        )
        if fixture.tolerance_kind == "format-quantization":
            self.assertEqual(  # type: ignore[attr-defined]
                fixture.tolerance,
                pixelformat.channel_tolerance(
                    pixelformat.PIXEL_FORMATS[fixture.conditions["pixel_format"]]
                ),
                "a format-quantization tolerance is the format's own, never a chosen number",
            )
        else:
            self.assertIsInstance(fixture.fuzz, (int, float))  # type: ignore[attr-defined]
            self.assertIsInstance(fixture.blur, int)  # type: ignore[attr-defined]

    def test_decodes_to_its_oracle(self) -> None:
        fixture = self.fixture
        cli = fixture.client()
        for step in fixture.steps():
            cli.dataReceived(gzip.decompress(step.read_bytes()))
            key = step.name.removesuffix(".bin.gz").split("-", 2)[2]
            expected = Image.open(SCENES_DIR / f"{key}.png")
            self.assertIsNotNone(cli.screen, f"{step.name}: no framebuffer after the update")
            mismatch = fixture.mismatch(cli.screen, expected)
            if mismatch is not None:
                self.fail(f"{fixture.name} {step.name}: {mismatch}")


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """unittest's own hook for building a suite: one case per fixture, named
    after it, so a failure's test id says which fixture failed.
    """
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestGoldens))
    for fixture in fixtures():
        name = f"TestGolden_{fixture.name.replace('-', '_')}"
        case = type(name, (GoldenReplay, unittest.TestCase), {"fixture": fixture})
        suite.addTest(case("test_says_which_kind_of_tolerance_it_carries"))
        suite.addTest(case("test_decodes_to_its_oracle"))
    return suite


if __name__ == "__main__":
    unittest.main()
