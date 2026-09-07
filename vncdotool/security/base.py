"""specs/security-handler-architecture.md is the design."""
from __future__ import annotations

from struct import unpack
from typing import Any, ClassVar, Generator

from twisted.python import log

from ..const import AuthTypes


class SecurityHandler:
    """One RFB security type: RFC 6143 section 7.2."""

    SECURITY_TYPE: ClassVar[AuthTypes]

    def handle(self, client: Any) -> Generator[int, bytes, bool]:
        """Yield the byte counts this security type needs, each satisfied in
        full, and return whether the connection proceeds to initialisation.
        The security type is already settled: written by the client on 3.7+,
        dictated by the server on 3.3.
        """
        raise NotImplementedError


def security_result(client: Any) -> Generator[int, bytes, bool]:
    """RFC 6143 section 7.1.3, and the reason string 3.8 adds on failure."""
    (result,) = unpack("!I", (yield 4))
    if result == 0:  # OK
        return True
    elif result == 1:  # failed
        reason = "authentication failed"
    elif result == 2:  # too many
        reason = "too many tries to log in"
    else:
        log.msg(f"unknown auth response ({result})")
        client.transport.loseConnection()
        return False

    if client._version < (3, 8):
        client.vncAuthFailed(reason)
    else:
        (waitfor,) = unpack("!I", (yield 4))
        client.requirePayload(waitfor)
        client.vncAuthFailed((yield waitfor))
    client.transport.loseConnection()
    return False
