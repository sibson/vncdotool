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

from vncdotool import client, pixelformat

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "goldens"
SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"


class Fixture:
    """One committed capture: the bytes, what they were captured at, and a
    client that replays them the way they were recorded.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.conditions = json.loads((path / "conditions.json").read_text())

    @property
    def group(self) -> str:
        """Fixtures of one server and encoding share this; the part after it
        is the format the capture asked for.
        """
        return self.name.rsplit("-", 1)[0]

    @property
    def tolerance(self) -> int:
        return self.conditions["tolerance"]

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
        requested = self.conditions.get("pixel_format")
        if requested is not None:
            cli.requested_pixel_format = pixelformat.PIXEL_FORMATS[requested]
        cli.dataReceived(gzip.decompress((self.path / "init.bin.gz").read_bytes()))
        return cli

    def replay(self) -> List[Tuple[str, Image.Image]]:
        """Every step, as (scene key, framebuffer)."""
        cli = self.client()
        screens = []
        for step in self.steps():
            cli.dataReceived(gzip.decompress(step.read_bytes()))
            assert cli.screen is not None, f"{step.name}: no framebuffer after the update"
            screens.append((step.name.removesuffix(".bin.gz").split("-", 2)[2], cli.screen.copy()))
        return screens

    def quantization(self) -> int:
        """Widest per-channel step the format this capture negotiated can hold.

        The negotiated format, not the announced one: a capture taken at a
        reduced format is quantized however wide the server's own pixels are.
        """
        fmt = self.client().pixel_format
        maxima = (fmt.redmax, fmt.greenmax, fmt.bluemax)
        if not all(maxima):
            raise AssertionError(f"{self.name}: no per-channel maxima in {fmt}")
        return max(255 // maximum for maximum in maxima)


def fixtures() -> List[Fixture]:
    return [
        Fixture(path)
        for path in sorted(FIXTURE_ROOT.iterdir())
        if (path / "conditions.json").exists()
    ]


def first_difference(actual: Image.Image, expected: Image.Image, tolerance: int) -> Optional[Tuple[int, int, tuple, tuple]]:
    left, right = actual.convert("RGB").tobytes(), expected.convert("RGB").tobytes()
    if actual.size != expected.size:
        raise AssertionError(f"decoded {actual.size}, expected {expected.size}")
    width, _ = actual.size
    for offset in range(0, len(left), 3):
        got, want = left[offset:offset + 3], right[offset:offset + 3]
        if any(abs(a - b) > tolerance for a, b in zip(got, want)):
            pixel = offset // 3
            return pixel % width, pixel // width, tuple(got), tuple(want)
    return None


class TestGoldens(unittest.TestCase):
    def test_at_least_one_fixture_is_committed(self) -> None:
        self.assertTrue(fixtures(), f"no golden fixtures under {FIXTURE_ROOT}; capture one with `make goldens`")


def fixture_groups() -> "dict[str, List[Fixture]]":
    groups: "dict[str, List[Fixture]]" = {}
    for fixture in fixtures():
        groups.setdefault(fixture.group, []).append(fixture)
    return groups


class CrossFormat:
    """The framebuffer does not depend on the format the server negotiated.

    Not a TestCase itself, so the loader collects it only through the
    subclasses load_tests builds.
    """

    reference: Fixture
    other: Fixture

    def test_decodes_the_same_as_its_pair(self) -> None:
        expected = dict(self.reference.replay())
        steps = self.other.replay()
        self.assertEqual(
            sorted(key for key, _ in steps), sorted(expected),
            f"{self.other.name} and {self.reference.name} cover different scenes",
        )
        tolerance = max(self.reference.quantization(), self.other.quantization())
        for key, screen in steps:
            difference = first_difference(screen, expected[key], tolerance)
            if difference is not None:
                x, y, got, want = difference
                self.fail(
                    f"{self.other.name} scene {key}: pixel ({x},{y}) decoded {got}, "
                    f"{self.reference.name} decoded {want} (tolerance {tolerance})"
                )


class GoldenReplay:
    """The body of a per-fixture case. Not a TestCase itself, so the loader
    collects it only through the subclasses load_tests builds.
    """

    fixture: Fixture

    def test_decodes_to_its_oracle(self) -> None:
        fixture = self.fixture
        tolerance = fixture.tolerance
        cli = fixture.client()
        for step in fixture.steps():
            cli.dataReceived(gzip.decompress(step.read_bytes()))
            key = step.name.removesuffix(".bin.gz").split("-", 2)[2]
            expected = Image.open(SCENES_DIR / f"{key}.png")
            self.assertIsNotNone(cli.screen, f"{step.name}: no framebuffer after the update")
            difference = first_difference(cli.screen, expected, tolerance)
            if difference is not None:
                x, y, got, want = difference
                self.fail(f"{fixture.name} {step.name}: pixel ({x},{y}) decoded {got}, expected {want}")


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    """unittest's own hook for building a suite: one case per fixture, named
    after it, so a failure's test id says which fixture failed.
    """
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestGoldens))
    for fixture in fixtures():
        name = f"TestGolden_{fixture.name.replace('-', '_')}"
        case = type(name, (GoldenReplay, unittest.TestCase), {"fixture": fixture})
        suite.addTest(case("test_decodes_to_its_oracle"))
    for members in fixture_groups().values():
        reference, *others = members
        for other in others:
            name = f"TestCrossFormat_{reference.name}_vs_{other.name}".replace("-", "_")
            case = type(
                name, (CrossFormat, unittest.TestCase),
                {"reference": reference, "other": other},
            )
            suite.addTest(case("test_decodes_the_same_as_its_pair"))
    return suite


if __name__ == "__main__":
    unittest.main()
