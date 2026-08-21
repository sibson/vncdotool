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


def fixtures() -> List[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if (path / "conditions.json").exists())


def conditions(fixture: Path) -> dict:
    return json.loads((fixture / "conditions.json").read_text())


def make_client(fixture: Optional[Path] = None) -> client.VNCDoToolClient:
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
    if fixture is not None:
        # The capture holds only the server's half, so the SetPixelFormat the
        # capturing client sent is not in it to replay: without this the
        # replay reads the server's announced format and, for any capture
        # taken at another one, every rectangle at the wrong width.
        requested = conditions(fixture).get("pixel_format")
        if requested is not None:
            cli.requested_pixel_format = pixelformat.PIXEL_FORMATS[requested]
    return cli


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


def replay(fixture: Path) -> List[Tuple[str, Image.Image]]:
    """Every step of a fixture, as (scene key, framebuffer)."""
    cli = make_client(fixture)
    cli.dataReceived(gzip.decompress((fixture / "init.bin.gz").read_bytes()))
    screens = []
    for step in sorted(fixture.glob("step-*.bin.gz")):
        cli.dataReceived(gzip.decompress(step.read_bytes()))
        assert cli.screen is not None, f"{step.name}: no framebuffer after the update"
        screens.append((step.name.removesuffix(".bin.gz").split("-", 2)[2], cli.screen.copy()))
    return screens


def quantization(fixture: Path) -> int:
    """Widest per-channel step the format this capture negotiated can hold.

    The negotiated format, not the announced one: a capture taken at a
    reduced format is quantized however wide the server's own pixels are.
    """
    cli = make_client(fixture)
    cli.dataReceived(gzip.decompress((fixture / "init.bin.gz").read_bytes()))
    fmt = cli.pixel_format
    maxima = (fmt.redmax, fmt.greenmax, fmt.bluemax)
    if not all(maxima):
        raise AssertionError(f"{fixture.name}: no per-channel maxima in {fmt}")
    return max(255 // maximum for maximum in maxima)


class TestGoldens(unittest.TestCase):
    def test_at_least_one_fixture_is_committed(self) -> None:
        self.assertTrue(fixtures(), f"no golden fixtures under {FIXTURE_ROOT}; capture one with `make goldens`")

    def test_every_fixture_holds_steps(self) -> None:
        """A capture that desynced distills to init and nothing else, and
        every check over its steps would then pass by iterating nothing.
        """
        for fixture in fixtures():
            with self.subTest(fixture=fixture.name):
                self.assertTrue(sorted(fixture.glob("step-*.bin.gz")), "fixture holds no steps")

    def test_paired_fixtures_were_captured_at_different_formats(self) -> None:
        """Two captures at the same format compare equal whatever the client
        does with a format, which would leave the check below asserting nothing.
        """
        groups: dict[str, List[Path]] = {}
        for fixture in fixtures():
            groups.setdefault(fixture.name.rsplit("-", 1)[0], []).append(fixture)
        for group, members in sorted(groups.items()):
            formats = [conditions(f).get("pixel_format") for f in members]
            with self.subTest(group=group):
                self.assertCountEqual(formats, set(formats), f"{group}: duplicate formats in {formats}")

    def test_a_scene_decodes_the_same_at_every_captured_format(self) -> None:
        """R3: the framebuffer does not depend on the format the server negotiated.

        Fixtures of one server and encoding differ only in the format their
        capture asked for, which is the last dash-separated part of the name.
        """
        groups: dict[str, List[Path]] = {}
        for fixture in fixtures():
            groups.setdefault(fixture.name.rsplit("-", 1)[0], []).append(fixture)

        for group, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            reference, *others = members
            expected = dict(replay(reference))
            for other in others:
                tolerance = max(quantization(reference), quantization(other))
                steps = replay(other)
                self.assertEqual(
                    sorted(key for key, _ in steps), sorted(expected),
                    f"{other.name} and {reference.name} cover different scenes",
                )
                for key, screen in steps:
                    with self.subTest(group=group, fixture=other.name, scene=key):
                        self.assertIn(key, expected, "scene missing from the reference capture")
                        difference = first_difference(screen, expected[key], tolerance)
                        if difference is not None:
                            x, y, got, want = difference
                            self.fail(
                                f"{other.name} scene {key}: pixel ({x},{y}) decoded {got}, "
                                f"{reference.name} decoded {want} (tolerance {tolerance})"
                            )


class GoldenReplay:
    """The body of a per-fixture case. Not a TestCase itself, so the loader
    collects it only through the subclasses load_tests builds.
    """

    fixture: Path

    def test_decodes_to_its_oracle(self) -> None:
        fixture = self.fixture
        tolerance = json.loads((fixture / "conditions.json").read_text())["tolerance"]
        cli = make_client()
        cli.dataReceived(gzip.decompress((fixture / "init.bin.gz").read_bytes()))
        for step in sorted(fixture.glob("step-*.bin.gz")):
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
    return suite


if __name__ == "__main__":
    unittest.main()
