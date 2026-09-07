from __future__ import annotations

from typing import Any, Generator

from ..const import MsgS2C
from .base import MessageHandler


class BellHandler(MessageHandler):
    MESSAGE = MsgS2C.BELL

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        client.bell()
        return
        yield  # pragma: no cover -- unreachable; keeps this a generator function
