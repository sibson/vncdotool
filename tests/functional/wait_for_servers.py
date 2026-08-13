#!/usr/bin/env python3
"""Wait until a group of VNC test servers can actually serve a screen.

Used as a readiness gate before the functional tests run, so a server that
is slow to become usable shows up here -- as a wait, with per-attempt
reasons -- rather than as a mysterious timeout inside a test.

Takes the same server group as capture_screenshots.py: ``docker``, ``os``,
or ``all`` (see vncservers.py). Exits non-zero if any server in the group
never became ready.
"""

import sys
from pathlib import Path
from typing import List

_HERE = Path(__file__).resolve().parent
# This module's own directory, for vncservers, plus the repo root, so the
# script works from a checkout without vncdotool having been pip installed.
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from vncservers import select_servers, wait_until_ready  # noqa: E402

from vncdotool import api  # noqa: E402

DEFAULT_GROUP = "os"


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else DEFAULT_GROUP
    ready = [wait_until_ready(server) for server in select_servers(group)]

    # api.connect() starts a background Twisted reactor thread that outlives
    # any individual client connection -- without stopping it here this
    # script hangs on exit instead of finishing.
    api.shutdown()

    return 0 if all(ready) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
