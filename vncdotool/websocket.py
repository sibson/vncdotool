"""RFB over a WebSocket, as noVNC, websockify, Proxmox and Selenoid serve it.

The address is a URL rather than a host and port, because the session is
identified by the path and query string as often as by the port.
"""

from __future__ import annotations

import enum
import socket
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Union
from urllib.parse import urlsplit, urlunsplit

from twisted.internet.endpoints import HostnameEndpoint, wrapClientTLS
from twisted.internet.error import ConnectionDone, ConnectionLost
from twisted.python.failure import Failure

if TYPE_CHECKING:
    from twisted.internet.defer import Deferred
    from twisted.internet.interfaces import IReactorCore, IStreamClientEndpoint
    from twisted.internet.protocol import ClientFactory


class Transport(enum.Enum):
    """Takes the place of a socket address family for a URL address."""

    WEBSOCKET = "websocket"


WEBSOCKET = Transport.WEBSOCKET

AddressFamily = Union[socket.AddressFamily, Transport]

DEFAULT_PORTS = {"ws": 80, "wss": 443}

INSTALL_HINT = (
    "ws:// and wss:// addresses need the autobahn WebSocket library, "
    "which is not installed: pip install 'vncdotool[websocket]'"
)

REDACTED = "?<redacted>"


class WebSocketUnavailable(ImportError):
    """Raised for a ws:// address when the websocket extra is not installed."""


def is_websocket_url(server: str) -> bool:
    scheme, sep, _ = server.partition("://")
    return bool(sep) and scheme.lower() in DEFAULT_PORTS


def parse_url(server: str) -> tuple[str, int]:
    """Split a ws:// or wss:// address into a normalised URL and its TCP port."""
    parts = urlsplit(server)
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise ValueError(server)
    if not parts.hostname:
        raise ValueError(server)

    port = parts.port or DEFAULT_PORTS[scheme]
    netloc = f"{parts.hostname}:{port}"
    # websockify and noVNC serve the root as a session of its own, and an
    # empty path is not a legal request-URI.
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, "")), port


def redact(address: str) -> str:
    """Hide anything a URL query string may carry, such as Selenoid's ?password=."""
    if not is_websocket_url(address):
        return address
    parts = urlsplit(address)
    query = REDACTED if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) + query


@lru_cache(maxsize=None)
def _wrapping_factory_class() -> type:
    """The autobahn factory that tunnels a stream factory over a WebSocket."""
    try:
        from autobahn.twisted.websocket import (
            WrappingWebSocketClientFactory,
            WrappingWebSocketClientProtocol,
        )
    except ImportError as exc:
        raise WebSocketUnavailable(INSTALL_HINT) from exc

    import txaio

    # autobahn logs the whole handshake, request-URI and query string included,
    # at debug.
    txaio.set_global_log_level("info")  # type: ignore[attr-defined]

    class ClosingProtocol(WrappingWebSocketClientProtocol):  # type: ignore[misc,valid-type]
        _proto: Any

        def loseConnection(self) -> None:
            # The wrapper closes with no status code, and autobahn then rejects
            # the peer's echo of it as an invalid close code 1005.
            self.sendClose(code=self.CLOSE_STATUS_CODE_NORMAL)

        def onClose(self, wasClean: bool, code: int | None, reason: str | None) -> None:
            # The wrapper hands the wrapped protocol None, where every other
            # Twisted transport hands it a Failure.
            error = ConnectionDone() if wasClean else ConnectionLost(reason)
            self._proto.connectionLost(Failure(error))

    class ClosingFactory(WrappingWebSocketClientFactory):  # type: ignore[misc,valid-type]
        protocol = ClosingProtocol

        def buildProtocol(self, addr: object) -> ClosingProtocol:
            proto = ClosingProtocol()
            proto.factory = self
            proto._proto = self._factory.buildProtocol(addr)
            proto._proto.transport = proto
            return proto

    return ClosingFactory


def connect(reactor: IReactorCore, factory: ClientFactory, url: str) -> Deferred:
    """Connect `factory` to `url`, tunnelling its byte stream over a WebSocket."""
    wrapping_factory = _wrapping_factory_class()

    parts = urlsplit(url)
    host = parts.hostname
    assert host is not None
    scheme = parts.scheme.lower()
    port = parts.port or DEFAULT_PORTS[scheme]

    endpoint: IStreamClientEndpoint = HostnameEndpoint(reactor, host, port)
    if scheme == "wss":
        try:
            # twisted.internet.ssl needs pyOpenSSL, which Twisted[tls] carries.
            from twisted.internet.ssl import optionsForClientTLS
        except ImportError as exc:
            raise WebSocketUnavailable(INSTALL_HINT) from exc

        # Verified against the platform trust store; SSL_CERT_FILE is how
        # OpenSSL is pointed at a private CA.
        endpoint = wrapClientTLS(optionsForClientTLS(host), endpoint)

    # A VNC stream is already compressed by its encoding, and permessage-deflate
    # is one more thing for a server to disagree about.
    return endpoint.connect(
        wrapping_factory(factory, url, reactor=reactor, enableCompression=False)
    )
