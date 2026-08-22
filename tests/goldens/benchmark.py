"""Time a decoder against a committed golden fixture. No Twisted in the loop.

Raw is the only encoding in live use, so it is the only one with a
before-and-after to regress against. Run this on the commit before a change
and on the change.

``--record`` appends a line to bench.jsonl per run: the timings, which are
only comparable against other lines carrying the same ``machine``, and the
call counts, which are comparable against every line.
"""
from __future__ import annotations

import argparse
import cProfile
import gc
import gzip
import json
import os
import platform
import pstats
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from unittest import mock

import vncdotool
from vncdotool import client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_ROOT = REPO_ROOT / "tests" / "unit" / "fixtures" / "goldens"
RECORD_PATH = REPO_ROOT / "bench.jsonl"
PACKAGE_ROOT = Path(vncdotool.__file__).resolve().parent


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


def _call_counts(init: bytes, steps: List[bytes]) -> Dict[str, int]:
    """Call counts for the vncdotool frames of one replay.

    Same bytes in, same counts out on any machine, so these compare across
    commits where the timings only compare within one machine. Keyed by
    file and function, never line number, so an edit above a function does
    not read as a change to it.
    """
    profiler = cProfile.Profile()
    profiler.enable()
    _replay(init, steps)
    profiler.disable()

    counts: Dict[str, int] = {}
    for (filename, _lineno, funcname), (_cc, nc, _tt, _ct, _cal) in pstats.Stats(profiler).stats.items():
        try:
            relative = Path(filename).resolve().relative_to(PACKAGE_ROOT)
        except ValueError:
            continue
        key = f"{relative.as_posix()}:{funcname}"
        counts[key] = counts.get(key, 0) + nc
    return dict(sorted(counts.items()))


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ("git", "-C", str(REPO_ROOT)) + args,
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def _record(path: Path, entry: Dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="tigervnc-raw-bgrx8888")
    parser.add_argument("--repeat", type=int, default=300)
    parser.add_argument("--profile", type=int, metavar="RUNS", default=0)
    parser.add_argument(
        "--record", nargs="?", const=str(RECORD_PATH), default=None, metavar="PATH",
        help=f"append one JSON line per run to PATH (default {RECORD_PATH.name})",
    )
    parser.add_argument(
        "--machine", default=os.environ.get("VNCDOTOOL_BENCH_MACHINE", platform.node()),
        help="label the timings belong to; only compare timings sharing one label",
    )
    args = parser.parse_args()

    fixture = FIXTURE_ROOT / args.fixture
    init = gzip.decompress((fixture / "init.bin.gz").read_bytes())
    steps = [gzip.decompress(p.read_bytes()) for p in sorted(fixture.glob("step-*.bin.gz"))]

    _replay(init, steps)  # warm PIL's plugin registry and the import graph

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(args.profile):
            _replay(init, steps)
        profiler.disable()
        stats = pstats.Stats(profiler)
        print(f"{args.fixture}: {len(steps)} updates x {args.profile} profiled runs")
        stats.sort_stats("tottime").print_stats(25)
        return 0

    gc.collect()
    timings = []
    for _ in range(args.repeat):
        start = time.perf_counter()
        _replay(init, steps)
        timings.append(time.perf_counter() - start)

    timings.sort()

    def us(fraction: float) -> float:
        return timings[int(fraction * (len(timings) - 1))] * 1e6

    print(f"{args.fixture}: {len(steps)} updates x {args.repeat} runs")
    # Microseconds, and p10 as well as the median: the replay is under a
    # millisecond, so a tenth of a millisecond is a tenth of the measurement,
    # and the median alone moves with whatever else the machine is doing.
    print(f"  best   {us(0.0):8.1f} us")
    print(f"  p10    {us(0.10):8.1f} us")
    print(f"  median {us(0.50):8.1f} us")

    if args.record:
        counts = _call_counts(init, steps)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain")),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "fixture": args.fixture,
            "updates": len(steps),
            "repeat": args.repeat,
            "best_us": round(us(0.0), 1),
            "p10_us": round(us(0.10), 1),
            "median_us": round(us(0.50), 1),
            "calls": counts,
            "calls_total": sum(counts.values()),
            "machine": args.machine,
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": f"{platform.system()}-{platform.machine()}",
        }
        path = Path(args.record)
        _record(path, entry)
        print(f"  recorded {entry['calls_total']} calls to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
