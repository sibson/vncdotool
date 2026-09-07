from __future__ import annotations

from typing import Any, Generator

from ..const import AuthTypes
from .base import SecurityHandler, security_result


class NoneHandler(SecurityHandler):
    SECURITY_TYPE = AuthTypes.NONE

    def handle(self, client: Any) -> Generator[int, bytes, bool]:
        # rfbproto, security type None: 3.3 and 3.7 pass straight to
        # initialisation; only from 3.8 does a SecurityResult follow.
        if client._version < (3, 8):
            return True
        return (yield from security_result(client))
