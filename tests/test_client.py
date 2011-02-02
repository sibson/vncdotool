import mock
from nose.plugins.skip import SkipTest

from vncdotool.client import VNCDoToolClient, VNCDoToolFactory
from vncdotool import rfb

class TestVNCDoToolClient(object):
    def setUp(self):
        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        # mock out a bunch of base class functions
        self.client.framebufferUpdateRequest = mock.Mock
        self.client.pointerEvent = mock.Mock()
        self.client.keyEvent = mock.Mock()

    def _tryPIL(self):
        try:
            import PIL
        except ImportError:
            raise SkipTest

    def test_vncConnectionMade(self):
        self.client.vncConnectionMade()
        factory = self.client.factory
        factory.clientConnectionMade.assert_called_once_with(self.client)

    def test_keyPress_single_alpha(self):
        client = self.client
        client.keyPress('a')
        client.keyEvent.assert_a_call_exists_with(ord('a'), down=1)
        client.keyEvent.assert_a_call_exists_with(ord('a'), down=0)

    def test_keyPress_multiple(self):
        client = self.client
        client.keyPress('ctrl-alt-del')

        # XXX doesn't ensure correct order
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_ControlLeft, down=1)
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_AltLeft, down=1)
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_Delete, down=1)
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_ControlLeft, down=0)
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_AltLeft, down=0)
        client.keyEvent.assert_a_call_exists_with(rfb.KEY_Delete, down=0)

    def test_captureScreen(self):
        self.client.vncConnectionMade()
        self.client.captureScreen('foo.png')

    def test_multiple_captures(self):
        self._tryPIL()
        self.client.vncConnectionMade()
        self.client.captureScreen('foo.png')
        self.client.captureScreen('bar.png')

    def test_expect_initial_match(self):
        self._tryPIL()
        self.client.vncConnectionMade()
        return # XXX
        self.client.expectScreen('bar.png')

    def test_expect_blocks_until_match(self):
        self._tryPIL()
        self.client.vncConnectionMade()
        return # XXX
        self.client.expectScreen('bar.png')
        # thousands of misses

class TestVNCDoToolFactory(object):

    def setUp(self):
        self.factory = VNCDoToolFactory()

    def test_init(self):
        assert self.factory.deferred

    def test_clientConnectionMade(self):
        deferred = mock.Mock()
        protocol = mock.Mock()
        self.factory.deferred = deferred

        self.factory.clientConnectionMade(protocol)

        deferred.callback.assert_called_once_with(protocol)
        assert self.factory.deferred is None

    def test_clientConnectionFailed(self):
        deferred = mock.Mock()
        self.factory.deferred = deferred
        reason = mock.Mock()
        connector = mock.Mock()

        self.factory.clientConnectionFailed(connector, reason)

        deferred.errback.assert_called_once_with(reason)
        assert self.factory.deferred is None
