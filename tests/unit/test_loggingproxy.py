"""Unit coverage for vnclog's proxy halves.

Both protocol classes are driven directly on mocked transports through a
scripted handshake, so the observer client runs for real without a reactor.
"""

from __future__ import annotations

import logging
from struct import pack
from unittest import TestCase, mock

from vncdotool import pixelformat
from vncdotool.const import AuthTypes
from vncdotool.loggingproxy import (
    VNCLoggingClientProxy,
    VNCLoggingServerFactory,
    VNCLoggingServerProxy,
)

VERSION_38 = b"RFB 003.008\n"
NATIVE = pixelformat.PIXEL_FORMATS["bgrx8888"]


class ProxyPair(TestCase):
    """A connected pair of proxy halves, taken through the handshake to the
    point where the observer client is decoding the server stream.
    """

    def setUp(self) -> None:
        self.factory = VNCLoggingServerFactory("localhost", 5900)
        self.factory.password_required = False

        self.server_proxy = VNCLoggingServerProxy()
        self.server_proxy.transport = mock.Mock()
        self.server_proxy.factory = self.factory
        self.client_proxy = VNCLoggingClientProxy()
        self.client_proxy.transport = mock.Mock()
        self.server_proxy.peer = self.client_proxy
        self.client_proxy.peer = self.server_proxy

        self.server_proxy.connectionMade()
        self.server_proxy.recorder = mock.Mock()

        self.client_proxy.dataReceived(VERSION_38)
        self.server_proxy.dataReceived(VERSION_38)
        self.client_proxy.dataReceived(bytes([1, AuthTypes.NONE]))
        self.server_proxy.dataReceived(bytes([AuthTypes.NONE]))
        self.client_proxy.dataReceived(b"\x00\x00\x00\x00")
        self.server_proxy.dataReceived(b"\x01")  # ClientInit: starts the observer
        self.client_proxy.dataReceived(
            pack("!HH16sI", 2, 1, NATIVE.to_bytes(), 4) + b"test"
        )

        self.observer = self.client_proxy.vnclog
        assert self.observer is not None


class TestObserverFailureIsReported(ProxyPair):

    def test_an_unreadable_server_message_is_reported_not_raised(self) -> None:
        """VNCDoToolClient reports a protocol error to its factory, and the
        observer's factory is the proxy's own.
        """
        unknown_message = bytes([250])

        with self.assertLogs("vncdotool.loggingproxy", level=logging.ERROR) as logged:
            self.client_proxy.dataReceived(unknown_message)

        self.assertIn("unknown message received", "\n".join(logged.output))
        self.assertTrue(self.observer._aborted)
        # The byte still reached the real client: only the observer gave up.
        self.server_proxy.transport.write.assert_any_call(unknown_message)
