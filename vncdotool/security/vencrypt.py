from __future__ import annotations

from struct import pack, unpack
from typing import Any, Generator, cast

from twisted.internet.interfaces import ITLSTransport
from twisted.python import log

from .. import vencrypt
from ..const import AuthTypes, VeNCryptSubtypes
from .base import SecurityHandler, security_result
from .errors import SecurityError


class VeNCryptHandler(SecurityHandler):
    SECURITY_TYPE = AuthTypes.VENCRYPT

    MAX_VERSION = (0, 2)

    def handle(self, client: Any) -> Generator[int, bytes, bool]:
        version = unpack("!BB", (yield 2))
        log.msg("Server offers VeNCrypt %d.%d" % version)
        if version < (0, 2):
            raise SecurityError("VeNCrypt %d.%d is not supported" % version)

        agreed = min(version, self.MAX_VERSION)
        client.transport.write(pack("!BB", *agreed))
        (ack,) = unpack("!B", (yield 1))
        if ack:
            raise SecurityError("server refused VeNCrypt %d.%d" % agreed)

        (count,) = unpack("!B", (yield 1))
        if not count:
            raise SecurityError("server offered no VeNCrypt subtypes")
        subtypes = unpack(f"!{count}I", (yield 4 * count))
        for subtype in subtypes:
            log.msg(f"Offered {VeNCryptSubtypes.lookup(subtype)!r}")

        policy = _policy(client)
        credentials = _credentials(client)
        chosen = vencrypt.choose(subtypes, policy, credentials)
        if chosen is None:
            raise SecurityError(vencrypt.refusal(subtypes, policy, credentials))

        log.msg(f"Requesting {chosen!r}")
        client._vencrypt_subtype = chosen
        client.transport.write(pack("!I", chosen))

        # The ack is sent for TLS and X509 subtypes only, which is every
        # subtype this client will choose.
        (ack,) = unpack("!B", (yield 1))
        if ack != 1:
            raise SecurityError(f"server refused {chosen!r}")
        if client._packet:
            # The TLS layer takes the socket over from here and has not sent
            # its ClientHello yet, so nothing can legitimately have arrived.
            raise SecurityError("server spoke before the TLS handshake")

        try:
            options = vencrypt.client_options(chosen, policy)
        except Exception as exc:
            raise SecurityError(f"cannot start TLS for VeNCrypt: {exc}")

        client._tls_handshake_pending = True
        cast(ITLSTransport, client.transport).startTLS(options)

        if chosen in vencrypt.VNC_AUTH_SUBTYPES:
            client._challenge = yield 16
            client.vncRequestPassword()
        elif chosen in vencrypt.PLAIN_AUTH_SUBTYPES:
            _send_plain(client)

        return (yield from security_result(client))


def _policy(client: Any) -> vencrypt.TLSPolicy:
    return vencrypt.TLSPolicy(
        hostname=client.factory.tls_hostname,
        ca_certs=client.factory.tls_ca_certs,
        allow_unverified=client.factory.tls_allow_unverified,
    )


def _credentials(client: Any) -> vencrypt.Credentials:
    return vencrypt.Credentials(
        username=client.factory.username, password=client.factory.password
    )


def _send_plain(client: Any) -> None:
    username = (client.factory.username or "").encode("utf-8")
    password = (client.factory.password or "").encode("utf-8")
    client.transport.write(pack("!II", len(username), len(password)))
    client.transport.write(username + password)
