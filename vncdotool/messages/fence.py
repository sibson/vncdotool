from __future__ import annotations

from struct import unpack
from typing import Any, Generator

from ..const import FenceFlags, MsgS2C
from .base import MessageHandler


class ServerFenceHandler(MessageHandler):
    MESSAGE = MsgS2C.SERVER_FENCE

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        flags, length = unpack("!xxxIB", (yield 8))
        payload = (yield length) if length else b""
        if flags & FenceFlags.REQUEST:
            # Masking, not clearing REQUEST alone, is what lets the server
            # learn which flags this client understands.
            known = FenceFlags.BLOCK_BEFORE | FenceFlags.BLOCK_AFTER | FenceFlags.SYNC_NEXT
            client.clientFence(FenceFlags(flags) & known, payload)
