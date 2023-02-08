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
