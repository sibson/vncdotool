from __future__ import annotations

from struct import unpack, unpack_from
from typing import Any, Generator, List, Tuple, cast

from ..const import MsgS2C
from .base import MessageHandler


class SetColourMapEntriesHandler(MessageHandler):
    MESSAGE = MsgS2C.SET_COLOUR_MAP_ENTRIES

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        # RFC 6143 7.6.2: 1 byte padding, U16 first-colour, U16
        # number-of-colours, then 6 bytes (R, G, B, each U16) per colour.
        (first_color, number_of_colors) = unpack("!xHH", (yield 5))
        payload_len = 6 * number_of_colors
        client.requirePayload(payload_len)
        block = yield payload_len
        colors = [
            unpack_from("!HHH", block, offset) for offset in range(0, len(block), 6)
        ]
        client.set_color_map(first_color, cast(List[Tuple[int, int, int]], colors))
