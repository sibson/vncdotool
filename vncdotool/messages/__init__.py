from __future__ import annotations

from typing import Dict, Type

from ..const import MsgS2C
from .base import MessageHandler
from .clipboard import ServerCutTextHandler
from .colourmap import SetColourMapEntriesHandler
from .fence import ServerFenceHandler
from .simple import BellHandler

HANDLERS: Dict[MsgS2C, Type[MessageHandler]] = {
    cls.MESSAGE: cls
    for cls in (
        SetColourMapEntriesHandler,
        BellHandler,
        ServerCutTextHandler,
        ServerFenceHandler,
    )
}


def for_connection() -> Dict[MsgS2C, MessageHandler]:
    return {message: cls() for message, cls in HANDLERS.items()}


__all__ = [
    "HANDLERS",
    "MessageHandler",
    "for_connection",
]
