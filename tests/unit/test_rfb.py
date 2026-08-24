import warnings
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

    def test_unknown_security_types_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._packet += (
            b"RFB 003.007\n"  # header
            b"\x01"  # num-auth-types
            b"\x7f"  # an auth type we do not support
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()

    def test_unknown_auth_type_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._packet += (
            b"RFB 003.003\n"  # header
            b"\x00\x00\x00\x7f"  # an auth type we do not support
        )
        self.client._handler()
        self.client.vncProtocolError.assert_called_once()

    def test_unknown_message_reports_protocol_error(self):
        self.client.vncProtocolError = mock.Mock()
        self.client._handleConnection(b"\x7f")
        self.client.vncProtocolError.assert_called_once()

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
        assert self.client._expected_handler == self.client._handleServerFence
        assert self.client._expected_len == 8

    def test_server_fence_request_gets_a_response_with_request_cleared(self):
        self.client._handleServerFence(
            b"\x00\x00\x00"  # padding
            b"\x80\x00\x00\x03"  # flags: REQUEST | BLOCK_AFTER | BLOCK_BEFORE
            b"\x00"  # payload length
        )
        self.client.transport.write.assert_called_once_with(
            b"\xf8\x00\x00\x00"  # CLIENT_FENCE, padding
            b"\x00\x00\x00\x03"  # flags: BLOCK_AFTER | BLOCK_BEFORE, REQUEST cleared
            b"\x00"  # payload length
        )

    def test_server_fence_request_clears_bits_the_client_does_not_understand(self):
        self.client._handleServerFence(
            b"\x00\x00\x00"  # padding
            b"\x80\x00\x00\x08"  # flags: REQUEST | an unknown bit
            b"\x00"  # payload length
        )
        self.client.transport.write.assert_called_once_with(
            b"\xf8\x00\x00\x00"
            b"\x00\x00\x00\x00"  # the unknown bit is cleared in the response
            b"\x00"
        )

    def test_server_fence_response_is_not_echoed_back(self):
        self.client._handleServerFence(
            b"\x00\x00\x00"  # padding
            b"\x00\x00\x00\x03"  # flags: BLOCK_AFTER | BLOCK_BEFORE, no REQUEST
            b"\x00"  # payload length
        )
        self.client.transport.write.assert_not_called()

    def test_server_fence_payload_is_echoed_back_with_the_response(self):
        self.client._handleServerFence(
            b"\x00\x00\x00"
            b"\x80\x00\x00\x00"  # REQUEST
            b"\x04"  # payload length
        )
        self.client._handleServerFencePayload(b"ping", 0x80000000)
        self.client.transport.write.assert_called_once_with(
            b"\xf8\x00\x00\x00\x00\x00\x00\x00\x04ping"
        )

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


class TestRFBClientSubclassWarning(TestCase):

    def test_overriding_updateRectangle_warns(self):
        with self.assertWarns(FutureWarning):
            class Sub(rfb.RFBClient):
                def updateRectangle(self, x, y, width, height, data):
                    pass

    def test_overriding_fillRectangle_warns(self):
        with self.assertWarns(FutureWarning):
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
