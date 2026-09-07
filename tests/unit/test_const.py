"""How protocol enums name themselves in messages a user has to act on."""

from unittest import TestCase

from vncdotool.const import (
    AuthTypes,
    Encoding,
    MsgS2C,
    Unknown,
    VeNCryptSubtypes,
)


class TestNamedValues(TestCase):

    def test_a_member_renders_as_its_name_and_number(self):
        assert str(MsgS2C.FILE_TRANSFER) == "FILE_TRANSFER (7)"

    def test_repr_renders_the_same_as_str(self):
        assert f"{MsgS2C.FILE_TRANSFER!r}" == "FILE_TRANSFER (7)"

    def test_a_security_type_takes_rfbprotos_spelling(self):
        assert str(AuthTypes.VENCRYPT) == "VeNCrypt (19)"
        assert str(AuthTypes.RSA_AES256) == "RSA-AES-256 (129)"
        assert str(AuthTypes.DIFFIE_HELLMAN) == "Diffie-Hellman (30)"

    def test_a_vencrypt_subtype_takes_rfbprotos_spelling(self):
        assert str(VeNCryptSubtypes.TLS_VNC) == "TLSVnc (258)"
        assert str(VeNCryptSubtypes.X509_VNC) == "X509Vnc (261)"
        assert str(VeNCryptSubtypes.PLAIN) == "Plain (256)"

    def test_a_type_with_no_rfbproto_name_keeps_its_member_name(self):
        assert str(AuthTypes.REALVNC_3) == "REALVNC_3 (3)"

    def test_a_vendor_number_renders_in_the_hex_rfbproto_writes_it_in(self):
        assert str(Encoding.PSEUDO_VMWARE_CURSOR) == "PSEUDO_VMWARE_CURSOR (0x574d5664)"

    def test_a_pseudo_encoding_renders_in_the_decimal_rfbproto_writes_it_in(self):
        assert str(Encoding.PSEUDO_CURSOR) == "PSEUDO_CURSOR (-239)"


class TestLookup(TestCase):

    def test_a_known_value_looks_up_to_its_member(self):
        assert AuthTypes.lookup(19) is AuthTypes.VENCRYPT

    def test_an_encoding_is_looked_up_at_its_signed_value(self):
        assert Encoding.lookup(0xFFFFFF11) is Encoding.PSEUDO_CURSOR

    def test_an_unknown_value_renders_without_a_repr_or_quotes(self):
        assert f"{AuthTypes.lookup(200)!r}" == "unknown (200)"

    def test_an_unknown_vendor_value_renders_in_hex(self):
        assert f"{Encoding.lookup(0x574D56AB)!r}" == "unknown (0x574d56ab)"

    def test_an_unknown_value_carries_a_name_to_build_tokens_from(self):
        assert Unknown(200).name == "unknown"

    def test_an_unknown_value_is_not_a_member_of_the_enum(self):
        """vnclog and the capture writer filter on this to drop what they
        cannot name."""
        assert not isinstance(Encoding.lookup(0x12345678), Encoding)
