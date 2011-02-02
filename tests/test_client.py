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
        self.client.framebufferUpdateRequest = mock.Mock()
        self.client.pointerEvent = mock.Mock()
        self.client.keyEvent = mock.Mock()

    def _tryPIL(self):
        try:
            import PIL
        except ImportError:
            raise SkipTest

    def test_vncConnectionMade(self):
        client = self.client
        client.vncConnectionMade()
        factory = client.factory
        factory.clientConnectionMade.assert_called_once_with(client)

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
        client = self.client
        client.vncConnectionMade()
        client.updates = mock.Mock()
        fname = 'foo.png'

        d = client.captureScreen(fname)
        d.addCallback.assert_called_once_with(client._captureSave, fname)
        assert client.framebufferUpdateRequest.called

    def test_captureSave(self):
        client = self.client
        client.screen = mock.Mock()
        fname = 'foo.png'
        r = client._captureSave(client.screen, fname)
        client.screen.save.assert_called_once_with(fname)
        assert r == client

    def test_expectScreen(self):
        self._tryPIL()

        client = self.client
        client.vncConnectionMade()
        client.updates = mock.Mock()
        client.image = mock.Mock()
        fname = 'something.png'

        d = client.expectScreen(fname, 5)
        assert client.framebufferUpdateRequest.called
        client.image.return_value.open.assert_called_once_with(fname)
        assert client.expected == client.image.return_value.open.return_value.histogram.return_value
        assert client.updates.get.called
        update = client.updates.get.return_value
        update.addCallback.assert_called_once_with(client._expectCompare, 5)

        assert d != update

    def test_expectCompareSuccess(self):
        client = self.client
        d = client.deferred = mock.Mock()
        client.expected = [ 2, 2, 2 ]
        image = mock.Mock()
        image.histogram.return_value = [ 1, 2, 3 ]
        client._expectCompare(image, 5)

        d.callback.assert_called_once_with(client)
        assert client.deferred is None

    def test_expectCompareFails(self):
        client = self.client
        client.deferred = mock.Mock()
        client.expected = [ 2, 2, 2 ]
        client.updates = mock.Mock()
        image = mock.Mock()
        image.histogram.return_value = [ 1, 2, 3 ]

        client._expectCompare(image, 0)

        assert not client.deferred.callback.called
        assert client.updates.get.called
        update = client.updates.get.return_value
        update.addCallback.assert_called_once_with(client._expectCompare, 0)


    def test_updateRectangeFirst(self):
        client = self.client
        client.updates = mock.Mock()
        client.image = mock.Mock()
        data = mock.Mock()

        client.updateRectangle(0, 0, 100, 200, data)

        image = client.image.return_value
        image.fromstring.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert client.updates.put(client.screen)
        assert client.screen == image.fromstring.return_value

    def test_updateRectangeRegion(self):
        client = self.client
        client.updates = mock.Mock()
        client.image = mock.Mock()
        client.screen = mock.Mock()
        client.screen.size = (100, 100)
        data = mock.Mock()

        client.updateRectangle(20, 10, 50, 40, data)

        image = client.image.return_value
        image.fromstring.assert_called_once_with('RGB', (50, 40), data, 'raw', 'RGBX')

        assert client.updates.put(client.screen)
        paste = client.screen.paste
        paste.assert_called_once_with(image.fromstring.return_value, (20, 10))


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
