"""What a capture does about the mouse pointer. specs/cursor.md is the design."""
from __future__ import annotations

from enum import Enum


class CursorMode(str, Enum):
    """The three states the protocol allows, one per `--cursor` value."""

    # Ask for the shape so the server stops painting, then drop it.
    NONE = "none"
    # Ask for nothing, and let the server composite its own pointer.
    SERVER = "server"
    # Ask for the shape and draw it, at the position the server reports.
    LOCAL = "local"

    def __str__(self) -> str:
        return self.value
