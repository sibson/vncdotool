"""Helpers for invoking the vncdotool command line entry points."""

from __future__ import annotations

import sys

import pexpect


def spawn_command(command: str, *args: str, **kwargs) -> pexpect.spawn:
    """Spawn a vncdotool CLI subprocess using ``python -m`` invocation."""
    argv = ["-m", "tests.functional.cli_runner", command]
    argv.extend(args)
    return pexpect.spawn(sys.executable, argv, **kwargs)
