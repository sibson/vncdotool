#!/usr/bin/env python3
"""Diagnostic only (diag/tightvnc-flat-wire): how often a fresh capture is flat.

Takes N captures of every server in a group, each through its own `vncdo`
process, round-robin across the servers, and prints one line per sample, a
per-server summary, and the wire trail of the first flat captures. Always
exits 0.

Usage: sample_flat_captures.py [os|docker|all] [N]
"""

import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import (  # noqa: E402
    VNCServer,
    capture_screenshot,
    distinct_colours,
    has_expected_content,
    print_wire_summary,
    probe_context,
    select_servers,
)

DEFAULT_SAMPLES = 20
TRAILS_PER_SERVER = 2


class Sample(NamedTuple):
    server: str
    index: int
    offset: float
    gap: Optional[float]
    duration: float
    flat: bool
    colour: Optional[str]
    colours: Optional[int]
    size: Optional[tuple]
    error: Optional[str]
    wire_log: Path


def take_sample(
    server: VNCServer, index: int, start: float, previous_end: Optional[float], tmp: Path
) -> Sample:
    png = tmp / f"{server.name}-{index:02d}.png"
    wire_log = tmp / f"{server.name}-{index:02d}.wire.log"
    began = time.monotonic()
    gap = None if previous_end is None else began - previous_end
    colours = size = colour = error = None
    flat = False
    try:
        with probe_context(server) as env:
            capture_screenshot(server, png, env=env, wire_log=wire_log)
        with Image.open(png) as image:
            colours = distinct_colours(image)
            size = image.size
            flat = not has_expected_content(server, colours)
            if flat:
                colour = "%02x%02x%02x" % image.convert("RGB").getpixel((0, 0))
    except Exception as exc:  # noqa: BLE001 - a failed capture is a data point too
        lines = str(exc).strip().splitlines() or [""]
        error = f"{type(exc).__name__}: {lines[0]}" + (f" ... {lines[-1]}" if len(lines) > 1 else "")
    return Sample(
        server.name, index, began - start, gap, time.monotonic() - began,
        flat, colour, colours, size, error, wire_log,
    )


def describe(sample: Sample) -> str:
    gap = "-" if sample.gap is None else f"{sample.gap:.2f}s"
    head = (
        f"[sample] {sample.server:<12} #{sample.index:02d} t=+{sample.offset:6.1f}s "
        f"gap={gap:>6} dur={sample.duration:5.2f}s"
    )
    if sample.error:
        return f"{head} ERROR {sample.error}"
    size = "x".join(str(n) for n in sample.size) if sample.size else "?"
    if sample.flat:
        return f"{head} FLAT {sample.colour} {size}"
    colours = ">256" if sample.colours is None else str(sample.colours)
    return f"{head} ok {colours} colours {size}"


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else "os"
    count = int(argv[2]) if len(argv) > 2 else DEFAULT_SAMPLES
    servers = select_servers(group)
    print(f"[sample] {count} captures each of {[s.name for s in servers]}, round-robin", flush=True)

    samples: Dict[str, List[Sample]] = {server.name: [] for server in servers}
    previous_end: Dict[str, Optional[float]] = {server.name: None for server in servers}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        start = time.monotonic()
        for index in range(count):
            for server in servers:
                sample = take_sample(server, index, start, previous_end[server.name], tmp)
                previous_end[server.name] = time.monotonic()
                samples[server.name].append(sample)
                print(describe(sample), flush=True)

        print(f"[sample] done in {time.monotonic() - start:.1f}s", flush=True)
        for server in servers:
            taken = samples[server.name]
            flats = [s for s in taken if s.flat]
            errors = [s for s in taken if s.error]
            print(
                f"[summary] {server.name}: N={len(taken)} flat={len(flats)} errors={len(errors)} "
                f"colours={sorted({s.colour for s in flats})} "
                f"indices={[s.index for s in flats]} "
                f"t={[round(s.offset, 1) for s in flats]} "
                f"gaps={[None if s.gap is None else round(s.gap, 2) for s in flats]}",
                flush=True,
            )
        for server in servers:
            for sample in [s for s in samples[server.name] if s.flat][:TRAILS_PER_SERVER]:
                print_wire_summary(server, sample.wire_log, f"sample-{sample.index:02d}")
    return 0


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:  # noqa: BLE001 - diagnostic step must never fail the job
        traceback.print_exc(file=sys.stdout)
    sys.exit(0)
