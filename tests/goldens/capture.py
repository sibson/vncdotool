"""Capture a golden fixture from a running fleet server.

Run by hand, via `make goldens`; CI replays the fixtures this writes.
"""
from __future__ import annotations

import argparse
import json
import select
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from tests.functional.vncservers import HOST, TIGERVNC, VNCDO, VNCLOG
from tests.goldens import distill, scenes
from vncdotool import pixelformat

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "unit" / "fixtures" / "goldens"
SCENE_VDO = Path(__file__).resolve().parent / "scene.vdo"
PROXY_PORT = 5999
PROXY_STARTUP_DEADLINE = 10.0
CAPTURE_DEADLINE = 60.0
# Budget for the whole scene script. A scene that never arrives fails here
# naming the image it waited for, rather than recording the one before it.
SCENE_DEADLINE = 30.0


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pixel-format",
        choices=sorted(pixelformat.PIXEL_FORMATS),
        default="bgrx8888",
        help="format the capturing client asks the server for [%(default)s]",
    )
    parser.add_argument(
        "--name",
        help="fixture directory name [tigervnc-raw-PIXEL_FORMAT]",
    )
    args = parser.parse_args()
    # The name carries the format because the cross-format check pairs
    # fixtures by everything before the last dash.
    name = args.name or f"tigervnc-raw-{args.pixel_format}"

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "capture.zip"
        proxy = _start_vnclog(archive)

        # scene.vdo waits on `expect scenes/<key>.png`, named relative to
        # itself, so the driver runs from the directory holding both.
        subprocess.run(
            [VNCDO, "--timeout", str(SCENE_DEADLINE), "--pixel-format", args.pixel_format,
             "-s", f"{HOST}::{PROXY_PORT}", SCENE_VDO.name],
            check=True, timeout=CAPTURE_DEADLINE, cwd=SCENE_VDO.parent,
        )
        proxy.wait(timeout=CAPTURE_DEADLINE)

        with zipfile.ZipFile(archive) as zipped:
            s2c = zipped.read("s2c.bin")
            meta = zipped.read("meta.json").decode()

        init, steps = distill.split(s2c)
        for step in steps:
            if step.key is None:
                raise SystemExit(f"step {step.index} carries no keysym patch; capture is unusable")

        directory = FIXTURE_ROOT / name
        if directory.exists():
            shutil.rmtree(directory)
        conditions = {
            "server": TIGERVNC.name,
            "pixel_format": args.pixel_format,
            "meta": json.loads(meta),
            "geometry": list(scenes.SIZE),
            "tolerance": 0,
        }
        distill.write_fixture(directory, init, steps, conditions)

        print(f"wrote {directory} ({len(steps)} steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
