from __future__ import annotations

from typing import Dict, Type

from ..const import AuthTypes
from .ard import DiffieHellmanHandler
from .base import SecurityHandler, security_result
from .errors import SecurityError
from .none import NoneHandler
from .vencrypt import VeNCryptHandler
from .vncauth import VNCAuthenticationHandler

HANDLERS: Dict[AuthTypes, Type[SecurityHandler]] = {
    cls.SECURITY_TYPE: cls
    for cls in (
        NoneHandler,
        VNCAuthenticationHandler,
        VeNCryptHandler,
        DiffieHellmanHandler,
    )
}


def for_connection() -> Dict[AuthTypes, SecurityHandler]:
    return {sec_type: cls() for sec_type, cls in HANDLERS.items()}


__all__ = [
    "HANDLERS",
    "SecurityError",
    "SecurityHandler",
    "for_connection",
    "security_result",
]
