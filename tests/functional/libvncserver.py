"""Utilities for building and running LibVNCServer example binaries."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "libvncserver.mk"
BUILD_ROOT = ROOT / ".vncdo"


def _examples_dir() -> Optional[Path]:
    """Return the directory containing compiled LibVNCServer examples."""
    if not BUILD_ROOT.exists():
        return None

    # Prefer the most recent build directory if multiple versions exist.
    candidates = sorted(BUILD_ROOT.glob("libvncserver-LibVNCServer-*/examples"))
    for path in reversed(candidates):
        if path.is_dir():
            return path
    return None


def _build_examples() -> None:
    """Invoke the makefile to build the required LibVNCServer examples."""
    subprocess.run(
        ["make", "-f", str(MAKEFILE), "libvnc-examples"],
        check=True,
        cwd=ROOT,
    )


@lru_cache(maxsize=None)
def _ensure_examples_dir() -> Path:
    """Ensure the LibVNCServer examples have been built and return their path."""
    directory = _examples_dir()
    if directory is None:
        _build_examples()
        directory = _examples_dir()
    if directory is None:
        raise RuntimeError(
            "LibVNCServer examples were not produced by libvncserver.mk build"
        )
    return directory


def ensure_example(name: str) -> Path:
    """Return the full path to the named LibVNCServer example binary."""
    examples = _ensure_examples_dir()
    executable = examples / name
    if not executable.exists():
        # Attempt to rebuild and check once more in case the default target changes.
        _build_examples()
        examples = _ensure_examples_dir()
        executable = examples / name
    if not executable.exists():
        raise FileNotFoundError(
            f"Example binary {name!r} was not created by libvncserver.mk"
        )
    return executable


@lru_cache(maxsize=None)
def _runtime_env() -> Dict[str, str]:
    """Environment variables required to run the LibVNCServer examples."""
    lib_root = _ensure_examples_dir().parent
    env = os.environ.copy()
    existing = env.get("LD_LIBRARY_PATH", "")
    if existing:
        env["LD_LIBRARY_PATH"] = f"{lib_root}:{existing}"
    else:
        env["LD_LIBRARY_PATH"] = str(lib_root)
    return env


def example_command(name: str, *args: str) -> Tuple[str, Tuple[str, ...], Dict[str, str]]:
    """Return command, arguments, and environment for launching an example binary."""
    executable = ensure_example(name)
    return str(executable), tuple(args), _runtime_env().copy()
