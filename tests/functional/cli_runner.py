"""Invoke vncdotool CLI entry points without installing the package."""

from __future__ import annotations

import sys
from typing import Callable

from vncdotool import command as cli

COMMANDS: dict[str, Callable[[], None]] = {
    'vncdo': cli.vncdo,
    'vnclog': cli.vnclog,
}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('usage: cli_runner.py <command> [args...]')

    cmd = sys.argv[1]
    try:
        entry = COMMANDS[cmd]
    except KeyError as exc:
        raise SystemExit(f'unknown vncdotool command: {cmd}') from exc

    sys.argv = [cmd, *sys.argv[2:]]
    entry()


if __name__ == '__main__':
    main()
