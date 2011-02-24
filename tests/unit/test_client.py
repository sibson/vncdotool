import mock
from nose.plugins.skip import SkipTest

from vncdotool import client
from vncdotool import rfb


@mock.isolate(client.VNCDoToolClient,
                excludes='math.sqrt,operator.add,client.KEYMAP')
class TestVNCDoToolClient(object):
    def setUp(self):
        self.client = client.VNCDoToolClient()
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
        cli = self.client
        cli.vncConnectionMade()
        factory = cli.factory
        factory.clientConnectionMade.assert_called_once_with(cli)

    def test_keyPress_single_alpha(self):
        cli = self.client
        cli.keyPress('a')
        cli.keyEvent.assert_a_call_exists_with(ord('a'), down=1)
        cli.keyEvent.assert_a_call_exists_with(ord('a'), down=0)

    def test_keyPress_multiple(self):
        cli = self.client
        cli.keyPress('ctrl-alt-del')

        # XXX doesn't ensure correct order
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_ControlLeft, down=1)
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_AltLeft, down=1)
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_Delete, down=1)
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_ControlLeft, down=0)
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_AltLeft, down=0)
        cli.keyEvent.assert_a_call_exists_with(rfb.KEY_Delete, down=0)

    def test_captureScreen(self):
        cli = self.client
        cli.vncConnectionMade()
        cli.updates = mock.Mock()
        fname = 'foo.png'

        d = cli.captureScreen(fname)
        d.addCallback.assert_called_once_with(cli._captureSave, fname)
        assert cli.framebufferUpdateRequest.called

    def test_captureSave(self):
        cli = self.client
        cli.screen = mock.Mock()
        fname = 'foo.png'
        r = cli._captureSave(cli.screen, fname)
        cli.screen.save.assert_called_once_with(fname)
        assert r == cli

    def test_expectScreen(self):
        self._tryPIL()

        cli = self.client
        cli.vncConnectionMade()
        cli.updates = mock.Mock()
        cli.image = mock.Mock()
        fname = 'something.png'

        d = cli.expectScreen(fname, 5)
        assert cli.framebufferUpdateRequest.called
        cli.image.return_value.open.assert_called_once_with(fname)
        assert cli.expected == cli.image.return_value.open.return_value.histogram.return_value
        assert cli.updates.get.called
        update = cli.updates.get.return_value
        update.addCallback.assert_called_once_with(cli._expectCompare, 5)

        assert d != update

    def test_expectCompareSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        image = mock.Mock()
        image.histogram.return_value = [1, 2, 3]
        cli._expectCompare(image, 5)

        d.callback.assert_called_once_with(cli)
        assert cli.deferred is None

    def test_expectCompareExactSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        image = mock.Mock()
        image.histogram.return_value = [2, 2, 2]
        cli._expectCompare(image, 0)

        d.callback.assert_called_once_with(cli)
        assert cli.deferred is None

    def test_expectCompareFails(self):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.updates = mock.Mock()
        image = mock.Mock()
        image.histogram.return_value = [1, 1, 1]

        cli._expectCompare(image, 0)

        assert not cli.deferred.callback.called
        assert cli.updates.get.called
        update = cli.updates.get.return_value
        update.addCallback.assert_called_once_with(cli._expectCompare, 0)

    def test_updateRectangeFirst(self):
        cli = self.client
        cli.updates = mock.Mock()
        cli.image = mock.Mock()
        data = mock.Mock()

        cli.updateRectangle(0, 0, 100, 200, data)

        image = cli.image.return_value
        image.fromstring.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert cli.updates.put(cli.screen)
        assert cli.screen == image.fromstring.return_value

    def test_updateRectangeRegion(self):
        cli = self.client
        cli.updates = mock.Mock()
        cli.image = mock.Mock()
        cli.screen = mock.Mock()
        cli.screen.size = (100, 100)
        data = mock.Mock()

        cli.updateRectangle(20, 10, 50, 40, data)

        image = cli.image.return_value
        image.fromstring.assert_called_once_with('RGB', (50, 40), data, 'raw', 'RGBX')

        assert cli.updates.put(cli.screen)
        paste = cli.screen.paste
        paste.assert_called_once_with(image.fromstring.return_value, (20, 10))

    def test_vncRequestPassword_prompt(self):
        cli = self.client
        cli.factory.password = None
        cli.sendPassword = mock.Mock()
        cli.vncRequestPassword()

        password = client.getpass.getpass.return_value
        assert client.getpass.getpass.called
        assert cli.factory.password == password
        cli.sendPassword.assert_called_once_with(password)

    def test_vncRequestPassword_attribute(self):
        cli = self.client
        cli.sendPassword = mock.Mock()
        cli.factory.password = 'mushroommushroom'
        cli.vncRequestPassword()
        cli.sendPassword.assert_called_once_with(cli.factory.password)


class TestVNCDoToolFactory(object):

    def setUp(self):
        self.factory = client.VNCDoToolFactory()

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
