import warnings
from struct import pack
from unittest import TestCase, mock

from vncdotool import rfb


class TestRFB(TestCase):

    def setUp(self) -> None:
        self.client = rfb.RFBClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

    def test_auth_invalid(self):
        self.client._packet += b"X"
        self.client._handler()
        self.client.transport.loseConnection.assert_called_once()

    def test_invalid_server_response_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._packet += b"X"
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        assert self.client._aborted

    def test_unknown_security_types_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._packet += (
            b"RFB 003.007\n"  # header
            b"\x01"  # num-auth-types
            b"\x7f"  # an auth type we do not support
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        assert self.client._aborted

    def test_unknown_auth_type_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._packet += (
            b"RFB 003.003\n"  # header
            b"\x00\x00\x00\x7f"  # an auth type we do not support
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        assert self.client._aborted

    def test_unknown_message_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._handleConnection(b"\x7f")
        self.client.vncProtocolError.assert_called_once()
        assert self.client._aborted

    def test_connection_refused_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._handleConnMessage(b"nope")
        self.client.vncProtocolError.assert_called_once()
        self.client.transport.loseConnection.assert_called_once()
        assert self.client._aborted

    def test_unknown_encoding_stops_processing_buffered_rectangles(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._handler = self.client._handleExpected
        self.client.rectangles = 3
        self.client.expect(self.client._handleRectangle, 12)
        unknown_encoding = 0x7F
        header = pack("!HHHHi", 0, 0, 1, 1, unknown_encoding)
        self.client._packet += header * 3
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        self.client.transport.loseConnection.assert_called_once()
        assert self.client._aborted
        assert not self.client._packet

    def test_auth_incmplete(self):
        self.client._packet += b"RFB 000.000"
        self.client._handler()
        self.client.transport.loseConnection.assert_not_called()

    def test_auth_invalid33(self):
        self.client._packet += (
            b"RFB 003.003\n"  # header
            b"\x00\x00\x00\x00"  # AuthTypes.INVALID
            b"\x00\x00\x00\x1a"  # length
            b"Too many security failures"
        )
        self.client._handler()
        assert self.client._version_server == (3, 3)
        assert self.client._version == (3, 3)
        self.client.transport.loseConnection.assert_called_once()

    def test_auth_none33(self):
        self.client._packet += (
            b"RFB 003.003\n"  # header
            b"\x00\x00\x00\x01"  # AuthTypes.NONE
        )
        self.client.factory.shared = 0
        self.client._handler()
        assert self.client._version_server == (3, 3)
        self.client.transport.write.assert_has_calls([
            mock.call(b"RFB 003.003\n"),
            mock.call(b"\x00"),  # shared
        ])

    def test_auth_none37(self):
        self.client._packet += (
            b"RFB 003.007\n"  # header
            b"\x01"  # num-auth-types
            b"\x01"  # AuthTypes.NONE
        )
        self.client.factory.shared = 0
        self.client._handler()
        assert self.client._version_server == (3, 7)
        self.client.transport.write.assert_has_calls([
            mock.call(b"RFB 003.007\n"),
            mock.call(b"\x01"),  # AuthTypes.NONE
            mock.call(b"\x00"),  # shared
        ])

    def test_server_fence_dispatches_from_handleConnection(self):
        self.client._handleConnection(b"\xf8")  # SERVER_FENCE
        assert self.client._expected_handler == self.client._pump
        assert self.client._expected_len == 8

    def test_clientFence(self):
        self.client.clientFence(rfb.FenceFlags.SYNC_NEXT, b"abc")
        self.client.transport.write.assert_called_once_with(
            b"\xf8\x00\x00\x00\x00\x00\x00\x04\x03abc"
        )

    def test_auth_none38(self):
        self.client._packet += (
            b"RFB 003.008\n"  # header
            b"\x01"  # num-auth-types
            b"\x01"  # AuthTypes.NONE
            b"\x00\x00\x00\x00"  # OK
        )
        self.client.factory.shared = 0
        self.client._handler()
        assert self.client._version_server == (3, 8)
        self.client.transport.write.assert_has_calls([
            mock.call(b"RFB 003.008\n"),
            mock.call(b"\x01"),  # AuthTypes.NONE
            mock.call(b"\x00"),  # shared
        ])

    def test_oversized_server_cut_text_length_is_a_diagnosed_disconnect(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._handler = self.client._handleExpected
        self.client.expect(self.client._handleConnection, 1)
        oversized = self.client.MAX_MESSAGE_PAYLOAD + 1
        self.client._packet += bytes([rfb.MsgS2C.SERVER_CUT_TEXT]) + pack(
            "!xxxI", oversized
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        self.client.transport.loseConnection.assert_called_once()
        assert self.client._aborted
        # never grew a buffer waiting for the declared length
        assert not self.client._packet

    def test_auth_vnc38(self):
        challenge = bytes(range(16))
        self.client._packet += (
            b"RFB 003.008\n"  # header
            b"\x01"  # num-auth-types
            b"\x02"  # AuthTypes.VNC_AUTHENTICATION
            + challenge
            + b"\x00\x00\x00\x00"  # OK
        )
        self.client.factory.password = "secret"
        self.client.factory.shared = 0
        self.client._handler()
        self.client.transport.write.assert_has_calls([
            mock.call(b"RFB 003.008\n"),
            mock.call(b"\x02"),  # AuthTypes.VNC_AUTHENTICATION
            mock.call(rfb.des_encrypt(rfb._vnc_des("secret"), challenge)),
            mock.call(b"\x00"),  # shared
        ])

    def test_password_sent_after_the_handshake_still_answers_the_challenge(self):
        challenge = bytes(range(16))
        self.client._packet += (
            b"RFB 003.008\n"  # header
            b"\x01"  # num-auth-types
            b"\x02"  # AuthTypes.VNC_AUTHENTICATION
            + challenge
        )
        self.client.factory.password = None
        self.client._handler()
        self.client.sendPassword("secret")
        self.client.transport.write.assert_called_with(
            rfb.des_encrypt(rfb._vnc_des("secret"), challenge)
        )

    def test_security_type_without_a_handler_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client.SUPPORTED_AUTHS = {rfb.AuthTypes.TIGHT}
        self.client._packet += (
            b"RFB 003.008\n"  # header
            b"\x01"  # num-auth-types
            b"\x10"  # AuthTypes.TIGHT
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()
        assert self.client._aborted

    def test_ardRequestCredentials_prompts_when_factory_has_no_username(self):
        self.client.factory = rfb.RFBFactory()
        with (
            mock.patch("builtins.input", return_value="alice") as input_,
            mock.patch("getpass.getpass", return_value="secret") as getpass_,
        ):
            self.client.ardRequestCredentials()
        input_.assert_called_once()
        getpass_.assert_called_once()
        assert self.client.factory.username == "alice"
        assert self.client.factory.password == "secret"


class TestRFBClientSubclassWarning(TestCase):

    def test_overriding_updateRectangle_warns(self):
        with self.assertWarnsRegex(FutureWarning, r"updateRectangle changed in 2\.0.*issues/385"):
            class Sub(rfb.RFBClient):
                def updateRectangle(self, x, y, width, height, data):
                    pass

    def test_overriding_fillRectangle_warns(self):
        with self.assertWarnsRegex(FutureWarning, r"fillRectangle changed in 2\.0.*issues/385"):
            class Sub(rfb.RFBClient):
                def fillRectangle(self, x, y, width, height, color):
                    pass

    def test_overriding_unrelated_method_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")

            class Sub(rfb.RFBClient):
                def bell(self):
                    pass

    def test_subclass_not_overriding_changing_hooks_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")

            class Sub(rfb.RFBClient):
                pass

    def test_override_from_vncdotool_module_does_not_warn(self):
        def updateRectangle(self, x, y, width, height, data):
            pass

        updateRectangle.__module__ = "vncdotool.client"

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            type("Sub", (rfb.RFBClient,), {"updateRectangle": updateRectangle})


class TestDesEncrypt(TestCase):

    def test_matches_the_published_des_vector(self):
        """The FIPS SP 800-17 single-DES vector, so this checks against
        published DES rather than against whatever this implementation
        happens to produce."""
        key = bytes.fromhex("0123456789ABCDEF")
        plaintext = bytes.fromhex("4E6F772069732074")

        self.assertEqual(
            rfb.des_encrypt(key, plaintext).hex().upper(),
            "3FA40E8A984D4815",
        )

    def test_emits_no_deprecation_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            rfb.des_encrypt(b"12345678", b"87654321")
