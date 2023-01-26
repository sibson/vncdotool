from unittest import TestCase

from vncdotool import pyDes

ZERO6 = b"\x00" * 6
ZERO8 = b"\x00" * 8
ZERO16 = b"\x00" * 16
ZERO24 = b"\x00" * 24


class Base:
    def test_ecb_normal(self):
        des = self.ALG(self.KEY)
        encrypted = des.encrypt(ZERO8)
        assert encrypted == b"\x8c\xa6M\xe9\xc1\xb1#\xa7", encrypted
        decrypted = des.decrypt(encrypted)
        assert decrypted == ZERO8, decrypted

    def test_ecb_pad0(self):
        des = self.ALG(self.KEY, pad=b"\x00", padmode=pyDes.PAD_NORMAL)
        encrypted = des.encrypt(ZERO6)
        assert encrypted == b"\x8c\xa6M\xe9\xc1\xb1#\xa7", encrypted
        decrypted = des.decrypt(encrypted)
        assert decrypted == b"", decrypted

    def test_ecb_pad1(self):
        des = self.ALG(self.KEY, pad=b"\x01", padmode=pyDes.PAD_NORMAL)
        encrypted = des.encrypt(ZERO6)
        assert encrypted == b"j\x8e\xf3\x0e\xf6\xf4^\xa5", encrypted
        decrypted = des.decrypt(encrypted)
        assert decrypted == ZERO6, decrypted

    def test_ecb_pkcs5(self):
        des = self.ALG(self.KEY, padmode=pyDes.PAD_PKCS5)
        encrypted = des.encrypt(ZERO8)
        assert encrypted == b"\x8c\xa6M\xe9\xc1\xb1#\xa7~B(\"w6f\xc0", encrypted
        decrypted = des.decrypt(encrypted)
        assert decrypted == ZERO8, decrypted

    def test_cbc_normal(self):
        des = self.ALG(self.KEY, mode=pyDes.CBC, IV=ZERO8)
        encrypted = des.encrypt(ZERO8)
        assert encrypted == b"\x8c\xa6M\xe9\xc1\xb1#\xa7", encrypted
        decrypted = des.decrypt(encrypted)
        assert decrypted == ZERO8, decrypted

    def test_invalid_key0(self):
        with self.assertRaises(ValueError):
            self.ALG(b"")

    def test_invalid_key6(self):
        with self.assertRaises(ValueError):
            self.ALG(ZERO6)

    def test_invalid_pad(self):
        with self.assertRaises(ValueError):
            self.ALG(self.KEY, pad=b"\x00", padmode=pyDes.PAD_PKCS5)

    def test_invalid_iv(self):
        with self.assertRaises(ValueError):
            self.ALG(self.KEY, mode=pyDes.CBC, IV=ZERO6)


class TestDES(TestCase, Base):
    ALG = pyDes.des
    KEY = ZERO8

    def test_invalid_cbc(self):
        with self.assertRaises(ValueError):
            self.ALG(self.KEY, mode=pyDes.CBC).encrypt(ZERO8)


class Test3DES16(TestCase, Base):
    ALG = pyDes.triple_des
    KEY = ZERO16


class Test3DES24(TestCase, Base):
    ALG = pyDes.triple_des
    KEY = ZERO24
