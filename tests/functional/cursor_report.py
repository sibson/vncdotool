#!/usr/bin/env python3
"""Render what the cursor tests measured, as a markdown table.

Post-processing only: it reads the captures and wire logs the cursor tests
already wrote, and connects to nothing. Run it after them, pass or fail.

Usage: cursor_report.py [docker|os|all] [> $GITHUB_STEP_SUMMARY]
"""

import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

from PIL import Image, ImageChops

_HERE = Path(__file__).resolve().parent
# Allow running straight from a checkout, without vncdotool installed.
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import (  # noqa: E402
    CURSOR_POSITIONS,
    VNCServer,
    cursor_box,
    parse_wire_log,
    screenshot_dir,
    select_servers,
)


class Row(NamedTuple):
    server: str
    paints: Optional[bool]
    shapes: List[str]

    @property
    def drawable(self) -> bool:
        return any(shape != "0x0" for shape in self.shapes)

    @property
    def verdict(self) -> str:
        if self.paints is None:
            return "not measured"
        if self.paints and self.drawable:
            return "paints **and** sends a shape -- `--localcursor` double-draws"
        if self.paints:
            return "paints and sends nothing usable -- the pointer stays in captures"
        if self.drawable:
            return "stops painting, shape available -- `--localcursor` restores it"
        return "no pointer in the framebuffer and none offered"


def measure(server: VNCServer) -> Row:
    shots = screenshot_dir()
    paints = None
    probe = shots / f"{server.name}-cursor-probe.png"
    away = shots / f"{server.name}-cursor-away.png"
    if probe.exists() and away.exists():
        with Image.open(probe) as a, Image.open(away) as b:
            occupied, vacated = a.convert("RGB"), b.convert("RGB")
            paints = any(
                ImageChops.difference(
                    occupied.crop(cursor_box(position, occupied.size)),
                    vacated.crop(cursor_box(position, occupied.size)),
                ).getbbox()
                is not None
                for position in CURSOR_POSITIONS
            )

    shapes = []
    for log in sorted(shots.glob(f"{server.name}-cursor-*.wire.log")):
        shapes += [
            f"{r.width}x{r.height}"
            for r in parse_wire_log(log)
            if r.encoding == "PSEUDO_CURSOR"
        ]
    return Row(server.name, paints, sorted(set(shapes)))


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else "os"
    rows = [measure(server) for server in select_servers(group)]

    print("## Cursor behaviour, measured\n")
    print("| server | paints the pointer | Cursor (-239) shape | what that means |")
    print("|---|---|---|---|")
    for row in rows:
        paints = {None: "not measured", True: "**yes**", False: "no"}[row.paints]
        shapes = ", ".join(row.shapes) or "none sent"
        print(f"| `{row.server}` | {paints} | {shapes} | {row.verdict} |")
    print("\nSee `specs/cursor.md`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
