#!/usr/bin/env python3
"""Capture a screenshot of every running VNC test server.

Which servers those are is chosen by the group named on the command line:
``docker`` (the default, the Docker Compose servers) or ``os`` (the
OS-hosted server on this machine, i.e. UltraVNC or Apple Screen Sharing).
See utils.py.

Screenshots land in the screenshots directory (``tests/servers/screenshots``
by default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) alongside a
self-contained ``index.html`` gallery with every capture inlined, so the
whole set can be eyeballed by opening one file -- locally with
``make screenshots``, or in CI by downloading the screenshots artifact.

When run inside GitHub Actions a summary table is also appended to the job
summary, so the run page says which servers were captured and how big each
screen was without downloading anything.

Servers that aren't running are skipped, and a capture failure is reported
rather than raised: this is a diagnostic aid and must not fail a build.
"""

import base64
import os
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

_HERE = Path(__file__).resolve().parent
# This module's own directory, for utils, plus the repo root, so the
# script works from a checkout without vncdotool having been pip installed.
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import (  # noqa: E402
    HOST,
    VNCServer,
    capture_screenshot,
    port_open,
    screenshot_dir,
    select_servers,
)

from vncdotool import api  # noqa: E402

DEFAULT_GROUP = "docker"


class Capture(NamedTuple):
    server: VNCServer
    path: Optional[Path]
    status: str


def capture(server: VNCServer, directory: Path) -> Capture:
    if not port_open(HOST, server.port):
        return Capture(server, None, f"skipped, nothing listening on port {server.port}")

    path = directory / f"{server.name}.png"
    try:
        capture_screenshot(server, path)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not fail the build
        return Capture(server, None, f"failed, {exc}")

    return Capture(server, path, "captured")


def describe(path: Path) -> str:
    """Human readable size of a captured screenshot, e.g. ``1024x768, 12.3 KiB``."""
    kib = path.stat().st_size / 1024
    try:
        from PIL import Image

        with Image.open(path) as image:
            return f"{image.width}x{image.height}, {kib:.1f} KiB"
    except Exception:  # noqa: BLE001 - fall back to the size we can always report
        return f"{kib:.1f} KiB"


def write_gallery(captures: List[Capture], directory: Path) -> Path:
    """Write a single self-contained HTML page showing every screenshot."""
    sections = []
    for item in captures:
        if item.path is None:
            body = f"<p class='missing'>{item.status}</p>"
        else:
            encoded = base64.b64encode(item.path.read_bytes()).decode("ascii")
            body = (
                f"<p class='meta'>{describe(item.path)}</p>"
                f"<img alt='{item.server.name} screenshot' "
                f"src='data:image/png;base64,{encoded}'>"
            )
        sections.append(
            f"<section><h2>{item.server.name}"
            f" <small>port {item.server.port}</small></h2>{body}</section>"
        )

    index = directory / "index.html"
    index.write_text(
        "<!doctype html>\n"
        "<html lang='en'><head><meta charset='utf-8'>"
        "<title>vncdotool test server screenshots</title>"
        "<style>"
        "body{font-family:sans-serif;margin:2rem;background:#fff;color:#111}"
        "section{margin-bottom:2.5rem}"
        "h2{margin-bottom:.25rem}"
        "small{font-weight:normal;color:#666}"
        ".meta{margin:.25rem 0;color:#666}"
        ".missing{color:#a00}"
        "img{max-width:100%;border:1px solid #ccc}"
        "</style></head><body>"
        "<h1>vncdotool test server screenshots</h1>"
        + "".join(sections)
        + "</body></html>\n",
        encoding="utf-8",
    )
    return index


def where_to_see_them() -> str:
    """One line pointing at the images, linked when the run is known.

    A job summary cannot show the images themselves: it renders no
    attachments, and the sanitizer drops `data:` URIs.
    """
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = os.environ.get("GITHUB_RUN_ID")
    artifact = "the `screenshots` artifact"
    if server and repo and run:
        artifact = f"[the `screenshots` artifact]({server}/{repo}/actions/runs/{run}#artifacts)"
    return f"Full size images are in {artifact}; open `index.html` from it to see them all on one page."


def write_job_summary(captures: List[Capture]) -> None:
    """Append a result table to the GitHub Actions job summary, if we're in one."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return

    rows = [
        "## VNC test server screenshots",
        "",
        "| server | port | result |",
        "| --- | --- | --- |",
    ]
    for item in captures:
        detail = describe(item.path) if item.path else item.status
        rows.append(f"| {item.server.name} | {item.server.port} | {detail} |")
    rows += ["", where_to_see_them(), ""]
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write("\n".join(rows))


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else DEFAULT_GROUP
    directory = screenshot_dir()
    captures = [capture(server, directory) for server in select_servers(group)]

    # api.connect() starts a background Twisted reactor thread that outlives
    # any individual client connection -- without stopping it here this
    # script hangs on exit instead of finishing.
    api.shutdown()

    for item in captures:
        location = item.path if item.path else item.status
        print(f"{item.server.name}: {location}")

    index = write_gallery(captures, directory)
    write_job_summary(captures)
    print(f"gallery: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
