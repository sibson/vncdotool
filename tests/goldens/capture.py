"""Capture a golden fixture from a running fleet server. Manual: `make goldens`.

Never runs in CI. CI runs the fixtures this writes.
"""
from __future__ import annotations

import argparse
import select
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.functional.vncservers import HOST, TIGERVNC_GOLDEN, VNCDO, VNCLOG  # noqa: E402
from tests.goldens import distill  # noqa: E402
from tests.servers import scenes  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "unit" / "fixtures" / "goldens"
PROXY_PORT = 5999
PROXY_STARTUP_DEADLINE = 10.0
CAPTURE_DEADLINE = 60.0
SCENE_ORDER = ["0", "s", "d", "x", "g", "p", "c", "f"]


def scene_script(directory: Path) -> Path:
    """The .vdo that drives the scenes -- it travels inside the archive."""
    lines = []
    for index, key in enumerate(SCENE_ORDER, start=1):
        lines.append(f"key {key}")
        # The app repaints on its own X event loop, so the capture request
        # can otherwise overtake the scene it is meant to record.
        lines.append("pause 0.3")
        lines.append(f"capture {directory}/driver-{index:02d}-{key}.png")
    path = directory / "scene.vdo"
    path.write_text("\n".join(lines) + "\n")
    return path


def image_digest(service: str) -> str:
    """Which image this fixture came from, so it can be rebuilt years later."""
    result = subprocess.run(
        ["docker", "compose", "-f", "tests/servers/docker-compose.yml", "images", "--format", "json", service],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def container_oracles(service: str, into: Path) -> dict:
    """Copy the scene app's own PNGs out of the container: the real oracle."""
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["docker", "compose", "-f", "tests/servers/docker-compose.yml", "cp",
         f"{service}:/oracles/.", str(into)],
        check=True,
    )
    return {path.name.split("-")[2].removesuffix(".png"): path for path in sorted(into.glob("oracle-*.png"))}


def _start_vnclog(archive: Path) -> subprocess.Popen:
    proxy = subprocess.Popen(
        [VNCLOG, "-s", f"{HOST}::{TIGERVNC_GOLDEN.port}", "--listen", str(PROXY_PORT),
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
    parser.add_argument("--name", default="tigervnc-raw-rgb888", help="fixture directory name")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        archive = work / "capture.zip"
        proxy = _start_vnclog(archive)

        subprocess.run(
            [VNCDO, "-s", f"{HOST}::{PROXY_PORT}", str(scene_script(work))],
            check=True, timeout=CAPTURE_DEADLINE,
        )
        proxy.wait(timeout=CAPTURE_DEADLINE)

        with zipfile.ZipFile(archive) as zipped:
            s2c = zipped.read("s2c.bin")
            meta = zipped.read("meta.json").decode()

        init, steps = distill.split(s2c)
        oracles = container_oracles(TIGERVNC_GOLDEN.name, work / "oracles")

        directory = FIXTURE_ROOT / args.name
        if directory.exists():
            shutil.rmtree(directory)
        conditions = {
            "server": TIGERVNC_GOLDEN.name,
            "image_digest": image_digest(TIGERVNC_GOLDEN.name),
            "meta": meta,
            "scene_order": SCENE_ORDER,
            "scene_script": scene_script(work).read_text(),
            "geometry": list(scenes.SIZE),
            "tolerance": 0,
        }
        distill.write_fixture(directory, init, steps, conditions)

        for step in steps:
            if step.key is None:
                raise SystemExit(f"step {step.index} carries no keysym patch; capture is unusable")
            oracle = oracles.get(step.key)
            if oracle is None:
                raise SystemExit(f"no oracle PNG for key {step.key!r}")
            Image.open(oracle).save(directory / f"step-{step.index:02d}-{step.key}.png")

        print(f"wrote {directory} ({len(steps)} steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
