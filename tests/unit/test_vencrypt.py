"""VeNCrypt subtype preference and TLS policy."""

import datetime
import tempfile
from pathlib import Path
from unittest import TestCase

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from OpenSSL import SSL
from twisted.internet.ssl import CertificateOptions

from vncdotool import vencrypt
from vncdotool.const import VeNCryptSubtypes

CREDENTIALS = vencrypt.Credentials(username="alice", password="s3kr1t")
VERIFYING = vencrypt.TLSPolicy(hostname="vnc.example.com")
INSECURE = vencrypt.TLSPolicy(hostname="vnc.example.com", allow_unverified=True)


def self_signed_pem() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "vnc.example.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


class TestSubtypeChoice(TestCase):

    def test_a_verified_tunnel_beats_an_anonymous_one(self):
        chosen = vencrypt.choose(
            [
                VeNCryptSubtypes.TLS_VNC,
                VeNCryptSubtypes.X509_VNC,
                VeNCryptSubtypes.PLAIN,
            ],
            INSECURE,
            CREDENTIALS,
        )

        assert chosen == VeNCryptSubtypes.X509_VNC

    def test_plain_over_a_bare_socket_is_never_chosen(self):
        chosen = vencrypt.choose([VeNCryptSubtypes.PLAIN], INSECURE, CREDENTIALS)

        assert chosen is None

    def test_refusing_an_anonymous_tunnel_does_not_fall_back_to_plain(self):
        chosen = vencrypt.choose(
            [VeNCryptSubtypes.TLS_VNC, VeNCryptSubtypes.PLAIN], VERIFYING, CREDENTIALS
        )

        assert chosen is None

    def test_plain_is_refused_for_sending_the_password_in_the_clear(self):
        reason = vencrypt.unusable(VeNCryptSubtypes.PLAIN, INSECURE, CREDENTIALS)

        assert reason is not None and "in the clear" in reason

    def test_anonymous_subtypes_are_unusable_by_default(self):
        for subtype in vencrypt.ANONYMOUS_SUBTYPES:
            with self.subTest(subtype=subtype):
                reason = vencrypt.unusable(subtype, VERIFYING, CREDENTIALS)
                assert reason is not None
                assert vencrypt.INSECURE_FLAG in reason

    def test_an_x509_subtype_needs_a_hostname_to_check_against(self):
        reason = vencrypt.unusable(
            VeNCryptSubtypes.X509_VNC, vencrypt.TLSPolicy(), CREDENTIALS
        )

        assert reason is not None and vencrypt.INSECURE_FLAG in reason

    def test_nothing_usable_names_every_subtype_that_was_offered(self):
        offered = [VeNCryptSubtypes.TLS_SASL, VeNCryptSubtypes.TLS_NONE]

        reason = vencrypt.refusal(offered, VERIFYING, CREDENTIALS)

        assert "TLS_SASL" in reason and "TLS_NONE" in reason


class TestClientOptions(TestCase):

    def test_x509_verifies_the_certificate_chain_by_default(self):
        options = vencrypt.client_options(VeNCryptSubtypes.X509_VNC, VERIFYING)

        # CertificateOptions on its own trusts everything; only the object
        # optionsForClientTLS builds checks a chain and a hostname.
        assert not isinstance(options, CertificateOptions)
        assert type(options).__name__ == "ClientTLSOptions"

    def test_the_insecure_flag_is_what_turns_verification_off(self):
        options = vencrypt.client_options(VeNCryptSubtypes.X509_VNC, INSECURE)

        assert isinstance(options, CertificateOptions)

    def test_anonymous_subtypes_offer_an_anonymous_key_exchange(self):
        options = vencrypt.client_options(VeNCryptSubtypes.TLS_NONE, VERIFYING)

        # Only a Connection can be asked what its Context settled on.
        ciphers = SSL.Connection(options.getContext(), None).get_cipher_list()
        assert any(name.startswith(("ADH-", "AECDH-")) for name in ciphers)

    def test_a_ca_bundle_contributes_every_certificate_it_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "ca.pem"
            bundle.write_bytes(self_signed_pem() + self_signed_pem())
            policy = VERIFYING._replace(ca_certs=str(bundle))

            options = vencrypt.client_options(VeNCryptSubtypes.X509_VNC, policy)

        assert type(options).__name__ == "ClientTLSOptions"

    def test_verification_without_a_hostname_is_an_error_not_a_bare_context(self):
        policy = VERIFYING._replace(hostname=None)

        with self.assertRaises(ValueError):
            vencrypt.client_options(VeNCryptSubtypes.X509_VNC, policy)

    def test_a_ca_file_holding_no_certificate_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "ca.pem"
            empty.write_bytes(b"")
            policy = VERIFYING._replace(ca_certs=str(empty))

            with self.assertRaises(ValueError):
                vencrypt.client_options(VeNCryptSubtypes.X509_VNC, policy)
