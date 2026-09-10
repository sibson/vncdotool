"""Subtype selection and TLS setup for VeNCrypt, security type 19."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

from OpenSSL import SSL
from twisted.internet.interfaces import IOpenSSLContextFactory
from twisted.internet.ssl import (
    Certificate,
    CertificateOptions,
    optionsForClientTLS,
    platformTrust,
    trustRootFromCertificates,
)
from zope.interface import implementer

from .const import AuthTypes, VeNCryptSubtypes

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

PLAIN_AUTH_SUBTYPES = frozenset(
    {
        VeNCryptSubtypes.TLS_PLAIN,
        VeNCryptSubtypes.X509_PLAIN,
    }
)

#: Ordered most protected first. Every member builds a TLS tunnel first:
#: rfbproto annotates the bare Plain subtype "should be never used".
PREFERENCE: Sequence[VeNCryptSubtypes] = (
    VeNCryptSubtypes.X509_VNC,
    VeNCryptSubtypes.X509_PLAIN,
    VeNCryptSubtypes.X509_NONE,
    VeNCryptSubtypes.TLS_VNC,
    VeNCryptSubtypes.TLS_PLAIN,
    VeNCryptSubtypes.TLS_NONE,
)

INSECURE_FLAG = "--tls-insecure-skip-verify"

# OpenSSL offers no anonymous ciphersuite at all until the security level is
# lowered.
_ANONYMOUS_CIPHERS = b"AECDH:ADH:@SECLEVEL=0"

_PEM_END = b"-----END CERTIFICATE-----"


class TLSPolicy(NamedTuple):
    hostname: str | None = None
    ca_certs: str | None = None
    allow_unverified: bool = False


class Credentials(NamedTuple):
    username: str | None = None
    password: str | None = None


def unusable(
    subtype: int, policy: TLSPolicy, credentials: Credentials
) -> str | None:
    """Why this client will not speak `subtype`, or None if it will."""
    if subtype == VeNCryptSubtypes.PLAIN:
        return "sends the password in the clear over an unencrypted socket"
    if subtype not in set(PREFERENCE):
        return "not implemented"
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


def name(subtype: int) -> str:
    """What to call `subtype` in a message."""
    # rfbproto: any normal security type may be listed among the subtypes,
    # which are numbered from 256 up.
    if subtype < VeNCryptSubtypes.PLAIN:
        return str(AuthTypes.lookup(subtype))
    return str(VeNCryptSubtypes.lookup(subtype))


def refusal(
    offered: Sequence[int], policy: TLSPolicy, credentials: Credentials
) -> str:
    reasons = "".join(
        f"\n  {name(subtype)}: {unusable(subtype, policy, credentials)}"
        for subtype in offered
    )
    return f"no usable VeNCrypt subtype, of the {len(offered)} offered:{reasons}"


def client_options(subtype: int, policy: TLSPolicy) -> Any:
    if subtype in ANONYMOUS_SUBTYPES:
        return _anonymous_options()
    if policy.allow_unverified:
        return _unverified_options()
    if policy.hostname is None:
        raise ValueError(
            f"no hostname to verify an X509 certificate against; "
            f"{INSECURE_FLAG} is what accepts one unverified"
        )
    return _verified_options(policy.hostname, policy.ca_certs)


def _verified_options(hostname: str, ca_certs: str | None) -> Any:
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
    return CertificateOptions()


def _anonymous_options() -> Any:
    @implementer(IOpenSSLContextFactory)
    class AnonymousTLSContextFactory:
        def __init__(self) -> None:
            self._context = SSL.Context(SSL.TLS_CLIENT_METHOD)
            # Pinned to exactly TLS 1.2: 1.3 defines no anonymous suite, and
            # SECLEVEL=0 below lifts the floor that would otherwise keep
            # OpenSSL from negotiating 1.0 or 1.1.
            self._context.set_min_proto_version(SSL.TLS1_2_VERSION)
            self._context.set_max_proto_version(SSL.TLS1_2_VERSION)
            self._context.set_cipher_list(_ANONYMOUS_CIPHERS)

        def getContext(self) -> Any:
            return self._context

    return AnonymousTLSContextFactory()
