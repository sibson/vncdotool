import warnings
from contextlib import contextmanager
from struct import pack
from unittest import TestCase, mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.utils import CryptographyDeprecationWarning

from vncdotool import security
from vncdotool.const import AuthTypes

SECURITY_OK = pack("!I", 0)
SECURITY_FAILED = pack("!I", 1)
SECURITY_TOO_MANY = pack("!I", 2)

# RFC 3526 group 14, a published 2048-bit safe prime.
MODP_2048 = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E08"
    "8A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B"
    "302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9"
    "A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE6"
    "49286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8"
    "FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C"
    "180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFF"
    "FFFFFFFF",
    16,
)


@contextmanager
def ffdh():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CryptographyDeprecationWarning)
        yield


def drive(handler, client, *blocks):
    """Drive a handler's generator the way RFBClient._pump does."""
    generator = handler.handle(client)
    for block in (None, *blocks):
        try:
            generator.send(block)
        except StopIteration as stop:
            return stop.value
    raise AssertionError("handler did not finish after the given blocks")


class TestHandlerRegistry(TestCase):

    def test_registry_keys_match_their_own_class(self):
        for sec_type, cls in security.HANDLERS.items():
            assert cls.SECURITY_TYPE == sec_type

    def test_for_connection_builds_one_instance_per_security_type(self):
        instances = security.for_connection()
        assert set(instances) == set(security.HANDLERS)
        for sec_type, handler in instances.items():
            assert isinstance(handler, security.HANDLERS[sec_type])

    def test_base_handler_has_no_implementation(self):
        with self.assertRaises(NotImplementedError):
            security.SecurityHandler().handle(mock.Mock())


class TestNoneHandler(TestCase):

    def setUp(self):
        self.handler = security.HANDLERS[AuthTypes.NONE]()
        self.client = mock.Mock()

    def test_no_security_result_before_38(self):
        self.client._version = (3, 7)
        assert drive(self.handler, self.client) is True

    def test_security_result_from_38(self):
        self.client._version = (3, 8)
        assert drive(self.handler, self.client, SECURITY_OK) is True

    def test_failure_from_38_does_not_proceed(self):
        self.client._version = (3, 8)
        outcome = drive(
            self.handler, self.client, SECURITY_FAILED, pack("!I", 4), b"nope"
        )
        assert outcome is False
        self.client.vncAuthFailed.assert_called_once_with(b"nope")


class TestSecurityResult(TestCase):

    def setUp(self):
        self.client = mock.Mock()

    def drive_result(self, *blocks):
        generator = security.security_result(self.client)
        for block in (None, *blocks):
            try:
                generator.send(block)
            except StopIteration as stop:
                return stop.value
        raise AssertionError("security_result did not finish")

    def test_ok_proceeds_and_keeps_the_connection(self):
        self.client._version = (3, 8)
        assert self.drive_result(SECURITY_OK) is True
        self.client.transport.loseConnection.assert_not_called()

    def test_failure_before_38_has_no_reason_string_on_the_wire(self):
        self.client._version = (3, 3)
        assert self.drive_result(SECURITY_FAILED) is False
        self.client.vncAuthFailed.assert_called_once_with("authentication failed")
        self.client.transport.loseConnection.assert_called_once()

    def test_too_many_before_38(self):
        self.client._version = (3, 3)
        assert self.drive_result(SECURITY_TOO_MANY) is False
        self.client.vncAuthFailed.assert_called_once_with("too many tries to log in")

    def test_too_many_from_38_reads_the_servers_reason(self):
        self.client._version = (3, 8)
        reason = b"too many security failures"
        outcome = self.drive_result(
            SECURITY_TOO_MANY, pack("!I", len(reason)), reason
        )
        assert outcome is False
        self.client.vncAuthFailed.assert_called_once_with(reason)
        self.client.transport.loseConnection.assert_called_once()

    def test_unknown_result_drops_the_connection_without_a_reason(self):
        self.client._version = (3, 8)
        assert self.drive_result(pack("!I", 7)) is False
        self.client.vncAuthFailed.assert_not_called()
        self.client.transport.loseConnection.assert_called_once()


class TestVNCAuthenticationHandler(TestCase):

    def setUp(self):
        self.handler = security.HANDLERS[AuthTypes.VNC_AUTHENTICATION]()
        self.client = mock.Mock()
        self.client._version = (3, 8)

    def test_challenge_is_left_on_the_client_for_sendPassword(self):
        challenge = bytes(range(16))
        assert drive(self.handler, self.client, challenge, SECURITY_OK) is True
        assert self.client._challenge == challenge
        self.client.vncRequestPassword.assert_called_once_with()

    def test_the_handler_never_waits_for_the_password(self):
        generator = self.handler.handle(self.client)
        generator.send(None)
        assert generator.send(bytes(16)) == 4


class TestDiffieHellmanHandler(TestCase):

    def setUp(self):
        self.handler = security.HANDLERS[AuthTypes.DIFFIE_HELLMAN]()
        self.client = mock.Mock()
        self.client._version = (3, 8)
        self.client.factory.username = "alice"
        self.client.factory.password = "secret"

    def test_credentials_decrypt_with_the_shared_secret(self):
        generator, key_len = 2, 256
        with ffdh():
            params = dh.DHParameterNumbers(p=MODP_2048, g=generator)
            server_private = params.parameters().generate_private_key()
        server_public = server_private.public_key().public_numbers().y

        outcome = drive(
            self.handler,
            self.client,
            pack("!HH", generator, key_len),
            MODP_2048.to_bytes(key_len, "big"),
            server_public.to_bytes(key_len, "big"),
            SECURITY_OK,
        )
        assert outcome is True
        self.client.ardRequestCredentials.assert_called_once_with()

        (sent,) = self.client.transport.write.call_args.args
        assert len(sent) == 128 + key_len
        ciphertext, client_public = sent[:128], sent[128:]

        with ffdh():
            shared = server_private.exchange(
                dh.DHPublicNumbers(
                    int.from_bytes(client_public, "big"), params
                ).public_key()
            )
        digest = hashes.Hash(hashes.MD5())
        digest.update(shared)
        decryptor = Cipher(algorithms.AES(digest.finalize()), modes.ECB()).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        assert plaintext[:64] == b"alice".ljust(64, b"\0")
        assert plaintext[64:] == b"secret".ljust(64, b"\0")

    def test_credentials_are_requested_before_anything_is_sent(self):
        self.client.ardRequestCredentials.side_effect = AssertionError("asked late")
        generator = self.handler.handle(self.client)
        generator.send(None)
        generator.send(pack("!HH", 2, 4))
        generator.send(b"\x00" * 4)
        with self.assertRaises(AssertionError):
            generator.send(b"\x00" * 4)
        self.client.transport.write.assert_not_called()
