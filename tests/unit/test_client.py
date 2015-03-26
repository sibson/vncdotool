from unittest import TestCase

from nose.plugins.skip import SkipTest
import mock

from vncdotool import client
from vncdotool import rfb


class TestVNCDoToolClient(TestCase):

    def setUp(self):
        self.isolation = mock.isolate.object(client.VNCDoToolClient,
                excludes='math.sqrt,operator.add,client.KEYMAP')
        self.isolation.start()

        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        # mock out a bunch of base class functions
        self.client.framebufferUpdateRequest = mock.Mock()
        self.client.pointerEvent = mock.Mock()
        self.client.keyEvent = mock.Mock()
        self.client.setEncodings = mock.Mock()

    def tearDown(self):
        if self.isolation:
            self.isolation.stop()
            self.isolation = None

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
        self.client.setEncodings.assert_called_once_with([client.rfb.RAW_ENCODING, client.rfb.PSEUDO_CURSOR_ENCODING])

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
        cli.screen = mock.Mock()
        cli.screen.size = (1024, 768)
        fname = 'something.png'

        region = (0 ,0, 11, 22)
        client.Image.open.return_value.size = region[2:]

        d = cli.expectScreen(fname, 5)
        assert cli.framebufferUpdateRequest.called

        client.Image.open.assert_called_once_with(fname)

        assert cli.expected == client.Image.open.return_value.histogram.return_value
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, region, 5)

    def test_expectCompareSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        image = mock.Mock()
        image.histogram.return_value = [1, 2, 3]
        image.crop.return_value = image
        result = cli._expectCompare(image, None, 5)
        assert result == cli

    def test_expectCompareExactSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        image = mock.Mock()
        image.histogram.return_value = [2, 2, 2]
        image.crop.return_value = image
        result = cli._expectCompare(image, None, 0)
        assert result == cli

    def test_expectCompareFails(self):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.framebufferUpdateRequest = mock.Mock()
        image = mock.Mock()
        image.histogram.return_value = [1, 1, 1]
        image.crop.return_value = image

        result = cli._expectCompare(image, None, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, None, 0)

    def test_expectCompareMismatch(self):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2]
        cli.framebufferUpdateRequest = mock.Mock()
        image = mock.Mock()
        image.histogram.return_value = [1, 1, 1]
        image.crop.return_value = image

        result = cli._expectCompare(image, None, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, None, 0)

    def test_updateRectangeFullScreen(self):
        cli = self.client
        cli.image = mock.Mock()
        data = mock.Mock()

        cli.updateRectangle(0, 0, 100, 200, data)

        client.Image.fromstring.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert cli.screen == client.Image.fromstring.return_value

    def test_updateRectangeRegion(self):
        cli = self.client
        cli.image = mock.Mock()
        cli.screen = mock.Mock()
        cli.screen.size = (100, 100)
        data = mock.Mock()

        cli.updateRectangle(20, 10, 50, 40, data)

        client.Image.fromstring.assert_called_once_with('RGB', (50, 40), data, 'raw', 'RGBX')

        paste = cli.screen.paste
        paste.assert_called_once_with(client.Image.fromstring.return_value, (20, 10))

    def test_commitUpdate(self):
        rects = mock.Mock()
        self.deferred = mock.Mock()
        self.client.deferred = self.deferred
        self.client.commitUpdate(rects)

        self.deferred.callback.assert_called_once_with(self.client.screen)

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

    def test_clientConnectionFailed(self):
        deferred = mock.Mock()
        self.factory.deferred = deferred
        reason = mock.Mock()
        connector = mock.Mock()

        self.factory.clientConnectionFailed(connector, reason)

        deferred.errback.assert_called_once_with(reason)
