from __future__ import annotations

import os
import warnings
from struct import unpack
from typing import Any, Generator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.utils import CryptographyDeprecationWarning

from ..const import AuthTypes
from .base import SecurityHandler, security_result
from .errors import SecurityError

CREDENTIAL_LEN = 64


class DiffieHellmanHandler(SecurityHandler):
    SECURITY_TYPE = AuthTypes.DIFFIE_HELLMAN

    def handle(self, client: Any) -> Generator[int, bytes, bool]:
        generator, key_len = unpack("!HH", (yield 4))
        modulus = yield key_len
        server_key = yield key_len

        client.ardRequestCredentials()

        client.transport.write(
            _encrypt(client, generator, key_len, modulus, server_key)
        )
        return (yield from security_result(client))


def _credential(name: str, value: str) -> bytes:
    # rfbproto pads each field to 64 bytes with random data rather than NULs,
    # and terminates it, so 63 bytes is the most one carries.
    encoded = value.encode("utf-8") + b"\0"
    if len(encoded) > CREDENTIAL_LEN:
        raise SecurityError(
            f"{name} is {len(encoded) - 1} bytes as UTF-8, over the "
            f"{CREDENTIAL_LEN - 1} this security type carries"
        )
    return encoded + os.urandom(CREDENTIAL_LEN - len(encoded))


def _encrypt(
    client: Any, generator: int, key_len: int, modulus: bytes, server_key: bytes
) -> bytes:
    userStruct = _credential("username", client.factory.username) + _credential(
        "password", client.factory.password
    )

    p = int.from_bytes(modulus, "big")
    sk = int.from_bytes(server_key, "big")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CryptographyDeprecationWarning)
        param_nums = dh.DHParameterNumbers(p=p, g=generator)
        server_public = dh.DHPublicNumbers(sk, param_nums).public_key()

    params = param_nums.parameters()
    private_key = params.generate_private_key()
    shared_key = private_key.exchange(server_public)

    h = hashes.Hash(hashes.MD5())
    h.update(shared_key)
    key_digest = h.finalize()

    cipher = Cipher(algorithms.AES(key_digest), modes.ECB())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(userStruct)
    ciphertext += encryptor.finalize()

    public_key = private_key.public_key()
    y = public_key.public_numbers().y.to_bytes(key_len, "big")

    return ciphertext + y
