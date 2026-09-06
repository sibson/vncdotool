"""Capture a golden fixture from a running fleet server.

Run by hand, via `make goldens`; CI replays the fixtures this writes.
"""
from __future__ import annotations

import argparse
import json
import math
import select
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

from tests.functional.utils import HOST, TIGERVNC, VNCDO, VNCLOG
from tests.goldens import distill, scenes
from vncdotool import decoders, imagematch, pixelformat

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "unit" / "fixtures" / "goldens"
SCENE_VDO = Path(__file__).resolve().parent / "scene.vdo"
PROXY_PORT = 5999
PROXY_STARTUP_DEADLINE = 10.0
CAPTURE_DEADLINE = 60.0
# Budget for the whole scene script. A scene that never arrives fails here
# naming the image it waited for, rather than recording the one before it.
SCENE_DEADLINE = 30.0

# Measured, not derived from the format: the keysym patch is a flat 48x48
# block, read back within this even at quality level 0, the worst tigervnc
# offers.
JPEG_PATCH_TOLERANCE = (8, 8, 8)

# What `expect` is given to sequence a lossy capture, which has to cover the
# worst quality level rather than the one being captured; derived in
# specs/expect-matching.md.
JPEG_FUZZ = 64
JPEG_BLUR = 2

# Headroom over what this capture measured, for the decode drifting a little
# under another libjpeg.
JPEG_FUZZ_MARGIN = 4


def _start_vnclog(archive: Path) -> subprocess.Popen:
    proxy = subprocess.Popen(
        [VNCLOG, "-s", f"{HOST}::{TIGERVNC.port}", "--listen", str(PROXY_PORT),
         "--capture-raw", str(archive)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
    )
    deadline = time.monotonic() + PROXY_STARTUP_DEADLINE
    ready = False
    while time.monotonic() < deadline and not ready:
        if proxy.poll() is not None:
            break
        rlist, _, _ = select.select([proxy.stderr], [], [], 0.2)
        if rlist and "accepting connections" in proxy.stderr.readline():
            ready = True
    if not ready:
        proxy.kill()
        proxy.wait(timeout=PROXY_STARTUP_DEADLINE)
        raise SystemExit(f"vnclog never listened on {PROXY_PORT}")
    return proxy


def _measured_fuzz(steps: list[distill.Step]) -> int:
    """How far this capture's own frames landed from their scenes.

    Recording the bound the driver ran under instead would assert only that
    the frames are somewhere inside a bound wide enough for quality level 0.
    """
    worst = max(
        imagematch.worst_delta(
            step.screen, Image.open(scenes.OUT_DIR / f"{step.key}.png"), JPEG_BLUR
        )
        for step in steps
    )
    return math.ceil(worst) + JPEG_FUZZ_MARGIN


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pixel-format",
        choices=sorted(pixelformat.PIXEL_FORMATS),
        required=True,
        help="format the capturing client asks the server for",
    )
    parser.add_argument(
        "--encoding",
        choices=sorted(decoders.ENCODING_NAMES),
        default="raw",
        help="encoding to offer the server, forcing it off Raw [raw]",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        help="offer this JPEG Quality Level, 0 (low) to 9 (high)",
    )
    parser.add_argument(
        "--name",
        help="fixture directory name [tigervnc-ENCODING-PIXEL_FORMAT]",
    )
    args = parser.parse_args()
    lossy = args.jpeg_quality is not None
    name = args.name or f"tigervnc-{args.encoding}-{args.pixel_format}"
    if lossy:
        patch_tolerance = JPEG_PATCH_TOLERANCE
    else:
        patch_tolerance = pixelformat.channel_tolerance(pixelformat.PIXEL_FORMATS[args.pixel_format])

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "capture.zip"
        proxy = _start_vnclog(archive)

        # scene.vdo waits on `expect scenes/<key>.png`, named relative to
        # itself, so the driver runs from the directory holding both.
        subprocess.run(
            [VNCDO, "--timeout", str(SCENE_DEADLINE), "--encodings", args.encoding]
            + (["--pixel-format", args.pixel_format] if args.pixel_format else [])
            + (
                [
                    "--jpeg-quality", str(args.jpeg_quality),
                    "--expect-fuzz", str(JPEG_FUZZ),
                    "--expect-blur", str(JPEG_BLUR),
                ] if lossy else []
            )
            + ["-s", f"{HOST}::{PROXY_PORT}", SCENE_VDO.name],
            check=True, timeout=CAPTURE_DEADLINE, cwd=SCENE_VDO.parent,
        )
        proxy.wait(timeout=CAPTURE_DEADLINE)

        with zipfile.ZipFile(archive) as zipped:
            s2c = zipped.read("s2c.bin")
            meta = zipped.read("meta.json").decode()

        init, steps = distill.split(s2c, args.pixel_format, patch_tolerance)
        if not steps:
            raise SystemExit("capture holds no framebuffer updates; the stream desynced")
        for step in steps:
            if step.key is None:
                raise SystemExit(f"step {step.index} carries no keysym patch; capture is unusable")

        directory = FIXTURE_ROOT / name
        if directory.exists():
            shutil.rmtree(directory)
        conditions = {
            "server": TIGERVNC.name,
            "encoding": args.encoding,
            "pixel_format": args.pixel_format,
            "meta": json.loads(meta),
            "geometry": list(scenes.SIZE),
            "tolerance_kind": "jpeg-lossy" if lossy else "format-quantization",
        }
        if lossy:
            conditions["jpeg_quality"] = args.jpeg_quality
            conditions["fuzz"] = _measured_fuzz(steps)
            conditions["blur"] = JPEG_BLUR
        else:
            conditions["tolerance"] = list(patch_tolerance)
        distill.write_fixture(directory, init, steps, conditions)

        print(f"wrote {directory} ({len(steps)} steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
