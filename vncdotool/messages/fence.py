from __future__ import annotations

from struct import unpack
from typing import Any, Generator

from ..const import FenceFlags, MsgS2C
from .base import MessageHandler


class ServerFenceHandler(MessageHandler):
    MESSAGE = MsgS2C.SERVER_FENCE

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        # rfbproto ServerFence: 3 bytes padding, U32 flags, U8 payload-length.
        flags, length = unpack("!xxxIB", (yield 8))
        payload = (yield length) if length else b""
        if flags & FenceFlags.REQUEST:
            # rfbproto ServerFence: masking to the flags handled here, rather
            # than just clearing Request, is what lets the server tell which
            # flags this client supports as new ones are defined.
            known = FenceFlags.BLOCK_BEFORE | FenceFlags.BLOCK_AFTER | FenceFlags.SYNC_NEXT
            client.clientFence(FenceFlags(flags) & known, payload)
