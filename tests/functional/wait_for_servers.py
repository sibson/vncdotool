#!/usr/bin/env python3
"""Wait until a group of VNC test servers can actually serve a screen.

Takes the same server group as capture_screenshots.py: ``docker``, ``os``,
or ``all``. Exits non-zero if any server never became ready.
"""

import sys
from pathlib import Path
from typing import List

_HERE = Path(__file__).resolve().parent
# This module's own directory, for utils, plus the repo root, so the
# script works from a checkout without vncdotool having been pip installed.
sys.path[:0] = [str(_HERE), str(_HERE.parents[1])]

from utils import fleet_mismatch, select_servers, wait_until_ready  # noqa: E402

from vncdotool import api  # noqa: E402

DEFAULT_GROUP = "os"


def main(argv: List[str]) -> int:
    group = argv[1] if len(argv) > 1 else DEFAULT_GROUP
    servers = select_servers(group)
    ready = [wait_until_ready(server) for server in servers]

    api.shutdown()  # the reactor thread outlives its clients; this script hangs without it

    mismatches = [message for message in (fleet_mismatch(server) for server in servers) if message]
    for message in mismatches:
        print(message)

    return 0 if all(ready) and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
