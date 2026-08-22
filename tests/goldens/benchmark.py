"""Time a decoder against a committed golden fixture. No Twisted in the loop.

Raw is the only encoding in live use, so it is the only one with a
before-and-after to regress against. Run this on the commit before a change
and on the change.
"""
from __future__ import annotations

import argparse
import gzip
import time
from pathlib import Path
from typing import List
from unittest import mock

from vncdotool import client

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "unit" / "fixtures" / "goldens"


def _make_client() -> client.VNCDoToolClient:
    cli = client.VNCDoToolClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    for name in ("shared", "nocursor", "pseudocursor", "pseudodesktop", "last_rect", "qemu_extended_key"):
        setattr(cli.factory, name, False)
    cli.factory.password = None
    return cli


def _replay(init: bytes, steps: List[bytes]) -> None:
    cli = _make_client()
    cli.dataReceived(init)
    for step in steps:
        cli.dataReceived(step)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="tigervnc-raw-bgrx8888")
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()

    fixture = FIXTURE_ROOT / args.fixture
    init = gzip.decompress((fixture / "init.bin.gz").read_bytes())
    steps = [gzip.decompress(p.read_bytes()) for p in sorted(fixture.glob("step-*.bin.gz"))]

    _replay(init, steps)  # warm PIL's plugin registry and the import graph

    timings = []
    for _ in range(args.repeat):
        start = time.perf_counter()
        _replay(init, steps)
        timings.append(time.perf_counter() - start)

    timings.sort()
    print(f"{args.fixture}: {len(steps)} updates x {args.repeat} runs")
    print(f"  best   {timings[0] * 1000:.1f} ms")
    print(f"  median {timings[len(timings) // 2] * 1000:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
