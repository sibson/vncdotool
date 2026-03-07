from unittest import TestCase, mock

from twisted.internet.defer import Deferred, fail, succeed
from twisted.python.failure import Failure

from vncdotool.api import ThreadedVNCClientProxy
from vncdotool.client import VNCDoToolClient, VNCDoToolFactory


class TestThreadedVNCClientProxy(TestCase):
    def setUp(self) -> None:
        self.factory = VNCDoToolFactory()
        self.protocol = mock.Mock(spec=VNCDoToolClient)
        self.proxy = ThreadedVNCClientProxy(self.factory, timeout=1)
        self.proxy.protocol = self.protocol

        # Fire the factory deferred with the protocol, simulating a connection
        self.factory.deferred.callback(self.protocol)

        # Make reactor.callFromThread execute the function immediately
        self.reactor_patcher = mock.patch("vncdotool.api.reactor")
        self.mock_reactor = self.reactor_patcher.start()
        self.mock_reactor.callFromThread.side_effect = lambda f, *a, **kw: f(*a, **kw)

    def tearDown(self) -> None:
        self.reactor_patcher.stop()

    def test_proxied_method_calls_bound_method(self) -> None:
        self.protocol.keyPress.return_value = self.protocol
        result = self.proxy.keyPress("a")
        self.protocol.keyPress.assert_called_once_with("a")
        assert result == self.protocol

    def test_proxied_method_passes_args_and_kwargs(self) -> None:
        self.protocol.captureScreen.return_value = self.protocol
        result = self.proxy.captureScreen("foo.png", incremental=True)
        self.protocol.captureScreen.assert_called_once_with(
            "foo.png", incremental=True
        )
        assert result == self.protocol

    def test_proxied_method_returning_deferred(self) -> None:
        d = succeed(self.protocol)
        self.protocol.captureScreen.return_value = d
        result = self.proxy.captureScreen("foo.png")
        self.protocol.captureScreen.assert_called_once_with("foo.png")
        assert result == self.protocol

    def test_multiple_sequential_calls(self) -> None:
        self.protocol.keyPress.return_value = self.protocol
        self.proxy.keyPress("a")
        self.proxy.keyPress("b")
        self.proxy.keyPress("c")
        assert self.protocol.keyPress.call_count == 3
        self.protocol.keyPress.assert_any_call("a")
        self.protocol.keyPress.assert_any_call("b")
        self.protocol.keyPress.assert_any_call("c")

    def test_chain_recovers_after_method_error(self) -> None:
        self.protocol.captureScreen.return_value = fail(
            Exception("screen not ready")
        )
        with self.assertRaises(Exception, msg="screen not ready"):
            self.proxy.captureScreen("foo.png")

        # Subsequent call should still work
        self.protocol.keyPress.return_value = self.protocol
        result = self.proxy.keyPress("a")
        self.protocol.keyPress.assert_called_once_with("a")
        assert result == self.protocol

    def test_chain_recovers_after_raised_exception(self) -> None:
        self.protocol.keyPress.side_effect = ValueError("bad key")
        with self.assertRaises(ValueError):
            self.proxy.keyPress("bad")

        # Subsequent call should still work
        self.protocol.keyPress.side_effect = None
        self.protocol.keyPress.return_value = self.protocol
        result = self.proxy.keyPress("a")
        assert result == self.protocol

    def test_non_callable_attribute(self) -> None:
        self.protocol.x = 42
        assert self.proxy.x == 42

    def test_missing_attribute_raises(self) -> None:
        with self.assertRaises(AttributeError):
            self.proxy.no_such_method()
