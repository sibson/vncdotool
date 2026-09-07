"""specs/decoder-architecture.md is the design this package mirrors."""
from __future__ import annotations

from typing import Any, ClassVar, Generator

from ..const import MsgS2C


class MessageHandler:
    """One server-to-client message: RFC 6143 section 7.6."""

    MESSAGE: ClassVar[MsgS2C]

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        """Yield the byte counts this message needs, each satisfied in full.
        The message-type byte has already been read.
        """
        raise NotImplementedError
