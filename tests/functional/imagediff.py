"""Compare a capture against an oracle image, and show what differed.

A failing comparison writes the captured image, the oracle it was compared
against and a per-pixel difference into ``screenshot_dir()/failures/``,
next to a self-contained ``index.html`` showing all three side by side.
CI uploads that directory as an artifact and links it from the pull
request, so a reviewer sees a channel swap, an offset paste and a wholly
wrong scene as three different pictures rather than as the same sentence.

The difference image is scaled so its largest channel delta reaches 255:
without that, quantization differences of two or three counts are a black
rectangle. Every caption therefore carries the unscaled numbers as well.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional
from unittest import TestCase

from PIL import Image, ImageChops

from .utils import screenshot_dir

FAILURES_DIRNAME = "failures"


class Difference:
    """What separates two same-sized images, and a picture of it."""

    def __init__(self, captured: Image.Image, oracle: Image.Image) -> None:
        self.delta = ImageChops.difference(captured.convert("RGB"), oracle.convert("RGB"))
        # Folded band by band rather than through convert("L"): that weights
        # the channels for luminance, and a delta of one count in blue would
        # round away to nothing.
        red, green, blue = self.delta.split()
        worst_band = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        self.worst = worst_band.getextrema()[1]
        self.pixels = sum(worst_band.histogram()[1:])

    @property
    def gain(self) -> int:
        return max(1, 255 // self.worst) if self.worst else 1

    def image(self) -> Image.Image:
        gain = self.gain
        return self.delta.point(lambda value: min(255, value * gain))

    def caption(self, total: int) -> str:
        share = 100.0 * self.pixels / total if total else 0.0
        scaling = f", shown at {self.gain}x" if self.gain > 1 else ""
        return (
            f"worst channel delta {self.worst}, "
            f"{self.pixels} of {total} pixels differ ({share:.2f}%){scaling}"
        )


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "comparison"


def _write_report(
    label: str, captured: Image.Image, oracle: Image.Image, summary: str, difference: Optional[Difference]
) -> Path:
    directory = screenshot_dir() / FAILURES_DIRNAME / _slug(label)
    directory.mkdir(parents=True, exist_ok=True)
    captured.save(directory / "captured.png")
    oracle.save(directory / "oracle.png")
    if difference is not None:
        difference.image().save(directory / "diff.png")
    (directory / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    _write_gallery(screenshot_dir() / FAILURES_DIRNAME)
    return directory


def _inline(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _panel(directory: Path, name: str, title: str) -> str:
    path = directory / f"{name}.png"
    if not path.exists():
        return ""
    return (
        f"<figure><figcaption>{title}</figcaption>"
        f"<img alt='{title}' src='{_inline(path)}'></figure>"
    )


def _write_gallery(root: Path) -> Path:
    """Rebuild the index over every failure recorded so far.

    Rebuilt from the directory rather than accumulated in memory, so the
    page is complete however the failures were spread across processes.
    """
    sections = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        note = directory / "summary.txt"
        summary = note.read_text(encoding="utf-8").strip() if note.exists() else ""
        panels = "".join(
            _panel(directory, name, title)
            for name, title in (("captured", "captured"), ("oracle", "oracle"), ("diff", "difference"))
        )
        sections.append(
            f"<section><h2>{directory.name}</h2>"
            f"<p class='meta'>{summary}</p><div class='row'>{panels}</div></section>"
        )

    index = root / "index.html"
    index.write_text(
        "<!doctype html>\n"
        "<html lang='en'><head><meta charset='utf-8'>"
        "<title>vncdotool image comparison failures</title>"
        "<style>"
        "body{font-family:sans-serif;margin:2rem;background:#fff;color:#111}"
        "section{margin-bottom:2.5rem}"
        "h2{margin-bottom:.25rem}"
        ".meta{margin:.25rem 0;color:#666}"
        ".row{display:flex;flex-wrap:wrap;gap:1rem}"
        "figure{margin:0}"
        "figcaption{color:#666;margin-bottom:.25rem}"
        "img{max-width:100%;border:1px solid #ccc;image-rendering:pixelated}"
        "</style></head><body>"
        "<h1>vncdotool image comparison failures</h1>"
        + "".join(sections)
        + "</body></html>\n",
        encoding="utf-8",
    )
    return index


def assert_images_match(
    test: TestCase,
    captured: Image.Image,
    oracle: Image.Image,
    label: str,
    tolerance: int = 0,
    message: str = "",
) -> None:
    """Fail unless no channel of `captured` differs from `oracle` by more than `tolerance`.

    A tolerance of 0 is byte equality. Either kind of failure -- a size
    mismatch or a pixel mismatch -- writes the images out first; see the
    module docstring.
    """
    detail = f": {message}" if message else ""

    if captured.size != oracle.size:
        summary = f"captured {captured.size[0]}x{captured.size[1]}, oracle {oracle.size[0]}x{oracle.size[1]}"
        where = _write_report(label, captured, oracle, summary, None)
        test.fail(f"{label}{detail}\n{summary}\nimages written to {where}")

    difference = Difference(captured, oracle)
    if difference.worst <= tolerance:
        return

    allowed = "byte for byte" if tolerance == 0 else f"more than the {tolerance} allowed"
    summary = difference.caption(captured.width * captured.height)
    where = _write_report(label, captured, oracle, summary, difference)
    test.fail(f"{label}{detail}\ndiffers {allowed}: {summary}\nimages written to {where}")
