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

from vncdotool import client

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "goldens"
SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"


def fixtures() -> List[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if (path / "conditions.json").exists())


def make_client() -> client.VNCDoToolClient:
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


class TestGoldens(unittest.TestCase):
    def test_at_least_one_fixture_is_committed(self) -> None:
        self.assertTrue(fixtures(), f"no golden fixtures under {FIXTURE_ROOT}; capture one with `make goldens`")

    def test_every_fixture_decodes_to_its_oracle(self) -> None:
        for fixture in fixtures():
            with self.subTest(fixture=fixture.name):
                conditions = json.loads((fixture / "conditions.json").read_text())
                tolerance = conditions["tolerance"]
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


if __name__ == "__main__":
    unittest.main()
