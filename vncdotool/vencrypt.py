"""Subtype selection and TLS setup for VeNCrypt, security type 19."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

from .const import VeNCryptSubtypes

#: TLS with an anonymous ciphersuite: the server sends no certificate.
ANONYMOUS_SUBTYPES = frozenset(
    {
        VeNCryptSubtypes.TLS_NONE,
        VeNCryptSubtypes.TLS_VNC,
        VeNCryptSubtypes.TLS_PLAIN,
    }
)

X509_SUBTYPES = frozenset(
    {
        VeNCryptSubtypes.X509_NONE,
        VeNCryptSubtypes.X509_VNC,
        VeNCryptSubtypes.X509_PLAIN,
    }
)

TLS_SUBTYPES = ANONYMOUS_SUBTYPES | X509_SUBTYPES

VNC_AUTH_SUBTYPES = frozenset(
    {VeNCryptSubtypes.TLS_VNC, VeNCryptSubtypes.X509_VNC}
)

#: Inner authentication is a username and password with no transform, so
#: the bare Plain subtype puts both on an unencrypted socket.
PLAIN_AUTH_SUBTYPES = frozenset(
    {
        VeNCryptSubtypes.PLAIN,
        VeNCryptSubtypes.TLS_PLAIN,
        VeNCryptSubtypes.X509_PLAIN,
    }
)

#: Ordered most protected first.
PREFERENCE: Sequence[VeNCryptSubtypes] = (
    VeNCryptSubtypes.X509_VNC,
    VeNCryptSubtypes.X509_PLAIN,
    VeNCryptSubtypes.X509_NONE,
    VeNCryptSubtypes.TLS_VNC,
    VeNCryptSubtypes.TLS_PLAIN,
    VeNCryptSubtypes.TLS_NONE,
    VeNCryptSubtypes.PLAIN,
)

INSECURE_FLAG = "--tls-insecure-skip-verify"

MISSING_TLS_SUPPORT = (
    "VeNCrypt's TLS subtypes need pyOpenSSL; install vncdotool[tls]"
)

# TLS 1.3 defines no anonymous ciphersuite, hence the 1.2 cap; OpenSSL
# withholds the ones that remain until the security level is lowered.
_ANONYMOUS_CIPHERS = b"AECDH:ADH:@SECLEVEL=0"

_PEM_END = b"-----END CERTIFICATE-----"


class TLSPolicy(NamedTuple):
    #: Name the certificate must be issued for; the address that was dialled.
    hostname: str | None = None
    #: PEM file of trust roots, replacing the platform trust store.
    ca_certs: str | None = None
    allow_unverified: bool = False


class Credentials(NamedTuple):
    username: str | None = None
    password: str | None = None


def tls_available() -> bool:
    try:
        import OpenSSL.SSL  # noqa: F401
        import twisted.protocols.tls  # noqa: F401
    except ImportError:
        return False
    return True


def unusable(
    subtype: int, policy: TLSPolicy, credentials: Credentials
) -> str | None:
    """Why this client will not speak `subtype`, or None if it will."""
    if subtype not in set(PREFERENCE):
        return "not implemented"
    if subtype in TLS_SUBTYPES and not tls_available():
        return MISSING_TLS_SUPPORT
    if subtype in ANONYMOUS_SUBTYPES and not policy.allow_unverified:
        return (
            f"anonymous TLS carries no certificate to verify, so it needs "
            f"{INSECURE_FLAG}"
        )
    if subtype in X509_SUBTYPES and not policy.allow_unverified and not policy.hostname:
        return (
            f"no hostname to check the certificate against, so it needs "
            f"{INSECURE_FLAG}"
        )
    if subtype in VNC_AUTH_SUBTYPES and credentials.password is None:
        return "no password given"
    if subtype in PLAIN_AUTH_SUBTYPES and (
        credentials.username is None or credentials.password is None
    ):
        return "no username and password given"
    return None


def choose(
    offered: Iterable[int], policy: TLSPolicy, credentials: Credentials
) -> VeNCryptSubtypes | None:
    available = set(offered)
    for subtype in PREFERENCE:
        if subtype in available and unusable(subtype, policy, credentials) is None:
            return subtype
    return None


def refusal(
    offered: Sequence[int], policy: TLSPolicy, credentials: Credentials
) -> str:
    reasons = ", ".join(
        f"{VeNCryptSubtypes.lookup(subtype)!r} {unusable(subtype, policy, credentials)}"
        for subtype in offered
    )
    return f"no usable VeNCrypt subtype: {reasons}"


def client_options(subtype: int, policy: TLSPolicy) -> Any:
    if subtype in ANONYMOUS_SUBTYPES:
        return _anonymous_options()
    if policy.allow_unverified:
        return _unverified_options()
    assert policy.hostname is not None, "unusable() admits no X509 subtype without one"
    return _verified_options(policy.hostname, policy.ca_certs)


def _verified_options(hostname: str, ca_certs: str | None) -> Any:
    from twisted.internet.ssl import (
        Certificate,
        optionsForClientTLS,
        platformTrust,
        trustRootFromCertificates,
    )

    if ca_certs is None:
        trust_root = platformTrust()
    else:
        pem = Path(ca_certs).read_bytes()
        certificates = [
            Certificate.loadPEM(block + _PEM_END)
            for block in pem.split(_PEM_END)[:-1]
        ]
        if not certificates:
            raise ValueError(f"no PEM certificate in {ca_certs}")
        trust_root = trustRootFromCertificates(certificates)

    return optionsForClientTLS(hostname, trustRoot=trust_root)


def _unverified_options() -> Any:
    from twisted.internet.ssl import CertificateOptions

    return CertificateOptions()


def _anonymous_options() -> Any:
    from OpenSSL import SSL
    from twisted.internet.interfaces import IOpenSSLContextFactory
    from zope.interface import implementer

    @implementer(IOpenSSLContextFactory)
    class AnonymousTLSContextFactory:
        def __init__(self) -> None:
            self._context = SSL.Context(SSL.TLS_CLIENT_METHOD)
            self._context.set_max_proto_version(SSL.TLS1_2_VERSION)
            self._context.set_cipher_list(_ANONYMOUS_CIPHERS)

        def getContext(self) -> Any:
            return self._context

    return AnonymousTLSContextFactory()
