from __future__ import annotations

from struct import unpack
from typing import Any, Generator

from ..const import MsgS2C
from .base import MessageHandler


class ServerCutTextHandler(MessageHandler):
    MESSAGE = MsgS2C.SERVER_CUT_TEXT

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        # RFC 6143 7.6.4: 3 bytes padding, U32 length, then length bytes.
        (length,) = unpack("!xxxI", (yield 7))
        client.requirePayload(length)
        client.copy_text((yield length).decode("iso-8859-1"))
