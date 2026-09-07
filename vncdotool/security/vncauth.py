from __future__ import annotations

from typing import Any, Generator

from ..const import AuthTypes
from .base import SecurityHandler, security_result


class VNCAuthenticationHandler(SecurityHandler):
    SECURITY_TYPE = AuthTypes.VNC_AUTHENTICATION

    def handle(self, client: Any) -> Generator[int, bytes, bool]:
        # RFC 6143 section 7.2.2: a 16-byte challenge, and the response goes
        # back whenever sendPassword runs, which a subclass may leave until
        # long after vncRequestPassword returns.
        client._challenge = yield 16
        client.vncRequestPassword()
        return (yield from security_result(client))
