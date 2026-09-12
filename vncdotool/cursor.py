"""What a capture does about the mouse pointer. specs/cursor.md is the design."""
from __future__ import annotations

from enum import Enum


class CursorMode(Enum):
    """The three states the protocol allows, one per `--cursor` value.

    Not a str subclass: nothing here compares by `==`, only `is`, and a
    plain string would equal a member without ever being one -- silently
    passing the `is not CursorMode.SERVER` / `is not CursorMode.LOCAL`
    checks in client.py as neither. `CursorMode(value)` is how a string
    becomes a real member; `api.connect()` is where that happens for a
    caller's own string.
    """

    # Ask for the shape so the server stops painting, then drop it.
    OMIT = "none"
    # Ask for nothing, and let the server composite its own pointer.
    SERVER = "server"
    # Ask for the shape and draw it, at the position the server reports.
    LOCAL = "local"

    def __str__(self) -> str:
        return self.value
